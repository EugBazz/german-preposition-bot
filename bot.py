import os
import random
from telegram.ext import Application, CommandHandler, CallbackQueryHandler
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from pyairtable import Api

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

class GermanVerbBot:
    def __init__(self, token, airtable_api_key, airtable_base_id):
        self.app = Application.builder().token(token).build()
        self.current_quiz = {}  # Store current quiz for each user
        self.user_stats = {}    # Store user statistics
        
        # Initialize Airtable
        self.api = Api(airtable_api_key)
        self.verbs_table = self.api.table(airtable_base_id, 'MainDB')  # Updated to your table name
        
        # Load words data from Airtable
        self.words_data = self.load_words_from_airtable()
        print(f"Loaded {len(self.words_data)} words from Airtable")
        
        self.setup_handlers()
    
    def parse_preposition_case(self, prep_string):
        """Parse 'auf + A' format into preposition and case"""
        if not prep_string:
            return None, None
        
        # Clean up the string and handle common formatting issues
        prep_string = prep_string.replace('+', ' + ').strip()  # Fix "über+A" -> "über + A"
        prep_string = ' '.join(prep_string.split())  # Remove extra spaces
            
        if ' + ' not in prep_string:
            return None, None
            
        parts = prep_string.split(' + ')
        if len(parts) != 2:
            return None, None
            
        preposition = parts[0].strip()
        case_code = parts[1].strip().upper()
        
        # Convert case codes to full names
        case_mapping = {
            'A': 'accusative',
            'D': 'dative', 
            'G': 'genitive'
        }
        
        case = case_mapping.get(case_code, 'unknown')
        return preposition, case
    
    def generate_wrong_options(self, correct_preposition):
        """Generate plausible wrong prepositions"""
        # Common German prepositions categorized by what they're often confused with
        common_prepositions = {
            'accusative': ['auf', 'für', 'gegen', 'durch', 'ohne', 'um', 'an', 'über'],
            'dative': ['mit', 'von', 'zu', 'bei', 'nach', 'aus', 'vor', 'an'],
            'both': ['in', 'über', 'unter', 'zwischen', 'neben', 'hinter', 'vor']
        }
        
        all_preps = set()
        for prep_list in common_prepositions.values():
            all_preps.update(prep_list)
        
        # Remove the correct preposition
        all_preps.discard(correct_preposition)
        
        # Return 3 random wrong options
        return random.sample(list(all_preps), min(3, len(all_preps)))

    def get_alternative_prepositions(self, word, current_preposition):
        """Find other valid prepositions for the same word"""
        alternatives = []
        for key, data in self.words_data.items():
            if (data['word'] == word and 
                data['preposition'] != current_preposition):
                alternatives.append({
                    'preposition': data['preposition'],
                    'prep_format': data['original_prep_format'],
                    'example': data.get('example_de') or data['example'],
                    'english': data.get('english_translation', '')
                })
        return alternatives
    
    def create_example_sentence(self, word, preposition, english_translation):
        """Create an example sentence from available data"""
        if english_translation:
            return f"I {english_translation} something. (Ich {word} {preposition} etwas.)"
        else:
            return f"Ich {word} {preposition} etwas."
    
    def load_words_from_airtable(self):
        """Load all words from Airtable and convert to our format"""
        try:
            # Get ALL records (handle pagination automatically)
            records = self.verbs_table.all()
            words_data = {}
            skipped_count = 0
            
            print(f"Found {len(records)} total records in Airtable")
            
            for record in records:
                fields = record['fields']
                
                # Debug: print first few records to see structure
                if len(words_data) < 3:
                    print(f"Record fields: {list(fields.keys())}")
                
                # Skip records that don't have required fields (but count them)
                if 'Word' not in fields or 'Preposition' not in fields:
                    skipped_count += 1
                    if skipped_count <= 5:  # Show first few skipped records
                        print(f"Skipped record - missing fields. Has: {list(fields.keys())}")
                    continue
                
                word = str(fields['Word']).strip() if fields['Word'] else ""
                prep_string = str(fields['Preposition']).strip() if fields['Preposition'] else ""
                
                # Skip if values are empty
                if not word or not prep_string:
                    skipped_count += 1
                    continue
                
                # Handle English translation and example - extract text if they're complex objects
                english_translation = fields.get('English Translation', '')
                if isinstance(english_translation, dict):
                    english_translation = english_translation.get('value', '') or english_translation.get('text', '')
                english_translation = str(english_translation).strip() if english_translation else ""
                
                example_de = fields.get('Example DE', '')
                if isinstance(example_de, dict):
                    example_de = example_de.get('value', '') or example_de.get('text', '')
                example_de = str(example_de).strip() if example_de else ""
                
                # Parse preposition and case
                preposition, case = self.parse_preposition_case(prep_string)
                if not preposition or not case:
                    skipped_count += 1
                    if skipped_count <= 5:
                        print(f"Skipped {word} - couldn't parse preposition: {prep_string}")
                    continue
                
                # Generate wrong options
                wrong_options = self.generate_wrong_options(preposition)
                
                # Use provided German example or create one
                if example_de:
                    example = example_de
                else:
                    example = self.create_example_sentence(word, preposition, english_translation)
                
                # Determine difficulty based on word complexity
                difficulty = 'beginner'
                if word.startswith('sich ') or len(word) > 8:
                    difficulty = 'intermediate'
                if 'ä' in word or 'ö' in word or 'ü' in word:
                    difficulty = 'advanced'
                
                # Create unique key for word + preposition combinations
                unique_key = f"{word}_{preposition}"
                
                words_data[unique_key] = {
                    'word': word,  # Store original word separately
                    'preposition': preposition,
                    'case': case,
                    'example': example,
                    'wrong_options': wrong_options,
                    'difficulty': difficulty,
                    'english_translation': english_translation,
                    'example_de': example_de,  # Store the German example
                    'original_prep_format': prep_string,
                    'record_id': record['id']
                }
            
            print(f"Successfully loaded: {len(words_data)} words")
            print(f"Skipped: {skipped_count} records")
            
            return words_data
            
        except Exception as e:
            print(f"Error loading from Airtable: {e}")
            # Fallback data in case Airtable is unavailable
            return {
                "achten": {
                    "preposition": "auf",
                    "case": "accusative",
                    "example": "I pay attention to something. (Ich achte auf etwas.)",
                    "wrong_options": ["für", "mit", "über"],
                    "difficulty": "beginner",
                    "english_translation": "pay attention to",
                    "original_prep_format": "auf + A"
                }
            }
    
    def refresh_words_data(self):
        """Refresh words data from Airtable"""
        self.words_data = self.load_words_from_airtable()
        print(f"Refreshed: {len(self.words_data)} words loaded")
    
    def setup_handlers(self):
        self.app.add_handler(CommandHandler("start", self.start))
        self.app.add_handler(CommandHandler("quiz", self.quiz))
        self.app.add_handler(CommandHandler("help", self.help))
        self.app.add_handler(CommandHandler("stats", self.stats))
        self.app.add_handler(CommandHandler("refresh", self.refresh_data))
        # Handle button clicks
        self.app.add_handler(CallbackQueryHandler(self.handle_button_click))
    
    async def start(self, update, context):
        user_id = update.effective_user.id
        # Initialize user stats
        if user_id not in self.user_stats:
            self.user_stats[user_id] = {
                'total_questions': 0,
                'correct_answers': 0,
                'streak': 0,
                'best_streak': 0
            }
        
        keyboard = [
            [InlineKeyboardButton("🎯 Start Quiz", callback_data="quiz_beginner")],
            [InlineKeyboardButton("📊 My Stats", callback_data="show_stats")],
            [InlineKeyboardButton("📚 Help", callback_data="help")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        welcome_text = f"""
🇩🇪 Welcome to German Preposition Practice Bot!

I'll help you practice German words with prepositions using your Airtable database.

📈 **Database**: {len(self.words_data)} words loaded
🎯 **Ready to practice?** Choose an option below!
        """
        await update.message.reply_text(welcome_text, reply_markup=reply_markup)
    
    async def help(self, update, context):
        keyboard = [
            [InlineKeyboardButton("🎯 Start Quiz", callback_data="quiz_beginner")],
            [InlineKeyboardButton("📊 My Stats", callback_data="show_stats")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        help_text = """
📚 **How to use this bot:**

🎯 **Quiz Modes:**
• Practice German words with prepositions
• Get instant feedback with examples

📊 **Features:**
• Track your progress and streaks
• Real-time data from your Airtable
• Support for verbs, nouns, and adjectives

🔧 **Commands:**
/quiz - Start a random quiz
/stats - View your statistics
/refresh - Update word database

Click a button below to get started!
        """
        
        if hasattr(update, 'callback_query'):
            await update.callback_query.edit_message_text(help_text, reply_markup=reply_markup)
        else:
            await update.message.reply_text(help_text, reply_markup=reply_markup)
    
    async def stats(self, update, context):
        user_id = update.effective_user.id
        if user_id not in self.user_stats:
            self.user_stats[user_id] = {
                'total_questions': 0,
                'correct_answers': 0,
                'streak': 0,
                'best_streak': 0
            }
        
        stats = self.user_stats[user_id]
        accuracy = (stats['correct_answers'] / max(stats['total_questions'], 1)) * 100
        
        keyboard = [
            [InlineKeyboardButton("🎯 New Quiz", callback_data="quiz_beginner")],
            [InlineKeyboardButton("🔄 Refresh Stats", callback_data="show_stats")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        stats_text = f"""
📊 **Your Statistics**

✅ **Correct Answers**: {stats['correct_answers']}/{stats['total_questions']}
🎯 **Accuracy**: {accuracy:.1f}%
🔥 **Current Streak**: {stats['streak']}
🏆 **Best Streak**: {stats['best_streak']}

📈 **Database**: {len(self.words_data)} words available

Keep practicing to improve your accuracy!
        """
        
        if hasattr(update, 'callback_query'):
            await update.callback_query.edit_message_text(stats_text, reply_markup=reply_markup)
        else:
            await update.message.reply_text(stats_text, reply_markup=reply_markup)
    
    async def refresh_data(self, update, context):
        """Admin command to refresh data from Airtable"""
        await update.message.reply_text("🔄 Refreshing word database from Airtable...")
        self.refresh_words_data()
        await update.message.reply_text(f"✅ Updated! Now have {len(self.words_data)} words loaded.")
    
    async def quiz(self, update, context):
        await self.start_quiz(update)
    
    async def start_quiz(self, update):
        user_id = update.effective_user.id
        
        # Use all words
        available_words = self.words_data
        
        # Pick a random word
        unique_key = random.choice(list(available_words.keys()))
        word_data = available_words[unique_key]
        word = word_data['word']
        
        # Get preposition and wrong options
        correct_prep = word_data["preposition"]
        wrong_preps = word_data["wrong_options"]
        
        # Mix them up
        all_options = [correct_prep] + wrong_preps
        random.shuffle(all_options)
        
        # Store the quiz data for this user
        self.current_quiz[user_id] = {
            'word': word,
            'correct_preposition': correct_prep,
            'example': word_data["example"],
            'case': word_data["case"],
            'original_prep_format': word_data["original_prep_format"],
            'english_translation': word_data.get("english_translation", ""),
            'example_de': word_data.get("example_de", "")
        }
        
        # Create inline keyboard with preposition buttons
        keyboard = []
        for prep in all_options:
            callback_data = f"answer_{prep}"
            button = InlineKeyboardButton(prep, callback_data=callback_data)
            keyboard.append([button])
        
        # Add action buttons
        keyboard.append([
            InlineKeyboardButton("🔄 New Quiz", callback_data="quiz_beginner"),
            InlineKeyboardButton("📊 Stats", callback_data="show_stats")
        ])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Create the quiz message
        quiz_text = f"""
🤔 Which preposition goes with "{word}"?

{word} ___ ...

📋 Choose the correct preposition:
        """
        
        if hasattr(update, 'callback_query') and update.callback_query:
            await update.callback_query.edit_message_text(quiz_text, reply_markup=reply_markup)
        elif hasattr(update, 'message') and update.message:
            await update.message.reply_text(quiz_text, reply_markup=reply_markup)
    
    async def handle_button_click(self, update, context):
        query = update.callback_query
        user_id = query.from_user.id
        
        # Acknowledge the button click
        await query.answer()
        
        # Initialize user stats if needed
        if user_id not in self.user_stats:
            self.user_stats[user_id] = {
                'total_questions': 0,
                'correct_answers': 0,
                'streak': 0,
                'best_streak': 0
            }
        
        # Handle different button actions
        if query.data.startswith("quiz_"):
            await self.start_quiz(update)
            
        elif query.data == "show_stats":
            await self.stats(update, context)
            
        elif query.data == "help":
            await self.help(update, context)
            
        elif query.data.startswith("answer_"):
            await self.handle_quiz_answer(query, user_id)
    
    async def handle_quiz_answer(self, query, user_id):
        # Check if user has an active quiz
        if user_id not in self.current_quiz:
            await query.edit_message_text("Start a new quiz first!")
            return
        
        quiz_data = self.current_quiz[user_id]
        
        # Extract the user's answer from callback data
        user_answer = query.data.replace("answer_", "")
        
        # Update stats
        self.user_stats[user_id]['total_questions'] += 1
        
        # Check if answer is correct
        is_correct = user_answer == quiz_data['correct_preposition']
        
        # Check for alternative valid prepositions for this word
        alternatives = self.get_alternative_prepositions(quiz_data['word'], quiz_data['correct_preposition'])
        user_found_alternative = any(alt['preposition'] == user_answer for alt in alternatives)
        
        if is_correct:
            self.user_stats[user_id]['correct_answers'] += 1
            self.user_stats[user_id]['streak'] += 1
            if self.user_stats[user_id]['streak'] > self.user_stats[user_id]['best_streak']:
                self.user_stats[user_id]['best_streak'] = self.user_stats[user_id]['streak']
            
            # Show additional context in success message
            context_info = ""
            if quiz_data.get("english_translation"):
                context_info += f"🇬🇧 English: {quiz_data['english_translation']}\n"
            
            # Use German example if available, otherwise use generated example
            example_text = quiz_data.get('example_de') or quiz_data['example']
            
            response = f"""
✅ Correct! 🎉

{quiz_data['word']} + {quiz_data['original_prep_format']}

💭 {example_text}

{context_info}
🔥 Streak: {self.user_stats[user_id]['streak']}
📊 Accuracy: {(self.user_stats[user_id]['correct_answers']/self.user_stats[user_id]['total_questions']*100):.1f}%
            """
        elif user_found_alternative:
            # User chose a valid alternative preposition
            self.user_stats[user_id]['correct_answers'] += 1
            self.user_stats[user_id]['streak'] += 1
            if self.user_stats[user_id]['streak'] > self.user_stats[user_id]['best_streak']:
                self.user_stats[user_id]['best_streak'] = self.user_stats[user_id]['streak']
            
            # Find the specific alternative they chose
            chosen_alt = next(alt for alt in alternatives if alt['preposition'] == user_answer)
            
            context_info = ""
            if quiz_data.get("english_translation"):
                context_info += f"🇬🇧 English: {quiz_data['english_translation']}\n"
            
            example_text = quiz_data.get('example_de') or quiz_data['example']
            
            response = f"""
✅ Also Correct! 🎉

You chose: {quiz_data['word']} + {user_answer} + {chosen_alt.get('prep_format', '').split(' + ')[1] if ' + ' in chosen_alt.get('prep_format', '') else ''}
💭 {chosen_alt['example']}

The quiz was asking for: {quiz_data['word']} + {quiz_data['original_prep_format']}
💭 {example_text}

💡 Both are correct! This word can take multiple prepositions with different meanings.

{context_info}
🔥 Streak: {self.user_stats[user_id]['streak']}
📊 Accuracy: {(self.user_stats[user_id]['correct_answers']/self.user_stats[user_id]['total_questions']*100):.1f}%
            """
        else:
            self.user_stats[user_id]['streak'] = 0
            
            # Show additional context in error message
            context_info = ""
            if quiz_data.get("english_translation"):
                context_info += f"🇬🇧 English: {quiz_data['english_translation']}\n"
            
            # Use German example if available, otherwise use generated example
            example_text = quiz_data.get('example_de') or quiz_data['example']
            
            # Show alternatives if they exist
            alternatives_text = ""
            if alternatives:
                alternatives_text = f"\n💡 Note: '{quiz_data['word']}' can also take other prepositions with different meanings."
            
            response = f"""
❌ Not quite right

The correct answer is: {quiz_data['word']} + {quiz_data['original_prep_format']}

💭 {example_text}

{context_info}{alternatives_text}

💪 Keep practicing! 
📊 Accuracy: {(self.user_stats[user_id]['correct_answers']/self.user_stats[user_id]['total_questions']*100):.1f}%
            """
        
        # Create continue buttons
        keyboard = [
            [InlineKeyboardButton("🔄 New Quiz", callback_data="quiz_beginner")],
            [InlineKeyboardButton("📊 My Stats", callback_data="show_stats")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Edit the original message to show the result
        await query.edit_message_text(response, reply_markup=reply_markup)
        
        # Clear the quiz for this user
        del self.current_quiz[user_id]
    
    def run(self):
        print("Bot is starting...")
        print(f"Loaded {len(self.words_data)} words from Airtable")
        self.app.run_polling()
        print("Bot stopped.")

def main():
    token = os.getenv('BOT_TOKEN')
    airtable_api_key = os.getenv('AIRTABLE_API_KEY')
    airtable_base_id = os.getenv('AIRTABLE_BASE_ID')
    
    if not all([token, airtable_api_key, airtable_base_id]):
        print("Error: Missing required environment variables")
        print("Make sure you have BOT_TOKEN, AIRTABLE_API_KEY, and AIRTABLE_BASE_ID in your .env file")
        return
    
    bot = GermanVerbBot(token, airtable_api_key, airtable_base_id)
    bot.run()

if __name__ == "__main__":
    main()
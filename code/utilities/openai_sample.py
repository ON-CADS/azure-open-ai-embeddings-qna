import logging
import os
from openai import AsyncAzureOpenAI
import json


class OpenAIManager:
    def __init__(self):
        # Azure OpenAI credentials
        self.api_key = os.environ.get('OPENAI_API_KEY')
        self.instance_name = os.environ.get('AZURE_OPENAI_INSTANCE_NAME')
        self.api_version = os.environ.get('OPENAI_API_VERSION')
        self.endpoint = os.environ.get('AZURE_OPENAI_ENDPOINT')
        self.deployment = os.environ.get('AZURE_CHAT_DEPLOYMENT', 'gpt-4')
        
        # Initialize AsyncAzureOpenAI client
        self.client = AsyncAzureOpenAI(
            azure_endpoint=self.endpoint,
            api_key=self.api_key,
            api_version=self.api_version
        )
    
    async def close(self):
        """Close the async client to prevent event loop errors"""
        try:
            await self.client.close()
            logging.info("AsyncAzureOpenAI client closed successfully")
        except Exception as e:
            logging.warning(f"Error closing AsyncAzureOpenAI client: {str(e)}")
    
    async def generate_completion(self, system_prompt, user_input):
        """
        Makes an asynchronous call to the OpenAI API
        
        Args:
            system_prompt (str): The system prompt to guide the model
            user_input (str): The user's input to process
            
        Returns:
            str: The generated text response
        """
        try:
            logging.info(f"Making request to model: {self.deployment}")
            
            # Use the deployment name instead of the model name
            response = await self.client.chat.completions.create(
                model=self.deployment,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_input}
                ],
                temperature=0,
                top_p=0.65,
                stream=False
            )
            
            return response.choices[0].message.content
        
        except Exception as e:
            error_msg = f"Error in API call: {str(e)}"
            logging.error(error_msg)
            return error_msg
    
    async def generate_cypher_query(self, schema_info, user_query, prompt_template, chat_history=None):
        """
        Generate a Cypher query based on the database schema and user query
        
        Args:
            schema_info (dict): Database schema information
            user_query (str): The user's natural language query
            prompt_template (str): The prompt template to use
            chat_history (str): Optional chat history context
            
        Returns:
            tuple: (cypher_query, llm_thinking) - The generated Cypher query and the LLM's thinking
        """
        # Prepare chat history text
        chat_history_text = chat_history if chat_history else "### Previous Conversation Context:\nNo previous conversation history available.\n"
        
        # Format the system prompt with schema information and chat history
        system_prompt = prompt_template.format(
            schema_info=json.dumps(schema_info, indent=2),
            chat_history=chat_history_text
        )
        
        response = await self.generate_completion(system_prompt, user_query)
        
        # Split the response into thinking and query parts
        if "---CYPHER QUERY---" in response:
            parts = response.split("---CYPHER QUERY---")
            llm_thinking = parts[0].strip()
            cypher_query = parts[1].strip()
        else:
            # Fallback for when the model doesn't follow the format correctly
            llm_thinking = "The model did not provide explicit thinking about the query."
            cypher_query = response
            
            # Try to extract query from code blocks if present
            if "```" in cypher_query:
                code_blocks = cypher_query.split("```")
                if len(code_blocks) >= 3:  # At least one complete code block
                    # Extract code from the first complete code block
                    cypher_query = code_blocks[1]
                    # Remove any language identifier
                    if cypher_query.startswith("cypher"):
                        cypher_query = cypher_query[6:].strip()
                    else:
                        cypher_query = cypher_query.strip()
                    
                    # The rest is probably the thinking
                    llm_thinking = code_blocks[0].strip()
        
        # Clean up the query if it still has markdown code blocks
        if "```" in cypher_query:
            cypher_query = cypher_query.split("```")[1]
            # Remove the language identifier if present
            if cypher_query.startswith("cypher"):
                cypher_query = cypher_query[6:].strip()
            else:
                cypher_query = cypher_query.strip()
        
        return cypher_query, llm_thinking

    async def validate_cypher_query(self, schema_info, user_query, cypher_query, prompt_template, chat_history=None):
        """
        Validate a Cypher query based on the database schema and user query
        
        Args:
            schema_info (dict): Database schema information
            user_query (str): The user's natural language query
            cypher_query (str): The generated Cypher query to validate
            prompt_template (str): The prompt template to use
            chat_history (str): Optional chat history context
            
        Returns:
            str: The validated/corrected Cypher query
        """
        # Prepare chat history text
        chat_history_text = chat_history if chat_history else "### Previous Conversation Context:\nNo previous conversation history available.\n"
        
        # Format the system prompt with schema, user query, cypher query, and chat history information
        system_prompt = prompt_template.format(
            schema_info=json.dumps(schema_info, indent=2),
            user_query=user_query,
            cypher_query=cypher_query,
            chat_history=chat_history_text
        )
        
        validated_query = await self.generate_completion(system_prompt, "Validate this Cypher query")
        
        # Extract the query from markdown code blocks if present
        if "```" in validated_query:
            validated_query = validated_query.split("```")[1]
            # Remove the language identifier if present
            if validated_query.startswith("cypher"):
                validated_query = validated_query[6:].strip()
            else:
                validated_query = validated_query.strip()
        
        return validated_query
    
    async def classify_intent(self, user_query):
        """
        Classify the user's intent to determine if the query is asking for help/general information,
        is a business question that requires database query, is out of scope, or wants to restart the session.
        
        Args:
            user_query (str): The user's natural language query
            
        Returns:
            str: Either 'help', 'business_query', 'out_of_scope', or 'session_restart'
        """
        system_prompt = """You are an intent classifier for an NPD (New Product Development) AI Agent. You must respond with EXACTLY ONE WORD and nothing else.

Classify the user's query into ONE category:

**session_restart** - User wants to start a new conversation, clear chat history, or restart the session.
Examples: "clear", "start new", "new chat", "restart", "reset", "start over", "begin again", "fresh start", "clear history", "new session", "start fresh"

**help** - User wants to know about THIS BOT's capabilities, how to use THIS BOT, needs examples, or guidance about THIS BOT.
Examples: "What can you do?", "Help", "Guide me", "How do I use this bot?", "Show examples", "What is this for?", "What are your capabilities?"

**business_query** - User asks about NPD/TD/IPD projects, milestones, customers, revenue, margins, roles, gates, or any business data. This includes follow-up questions that reference previous context.
Examples: 
- "Who are customers for N07P6?"
- "List TD projects"
- "Revenue for N088P?"
- "Who is PM for N08ML?"
- "Who is EPO for N08ML?"
- "Who is the EPO?" (follow-up question)
- "What is the margin?" (follow-up question)
- "What is the revenue?" (follow-up question)
- "What about revenue?" (follow-up question)
- "Show me the milestones"
- "What is the status?"
- "Who manages it?"
- "What are the gates?"
- "Tell me more about it"
- "What is the forecast?"
- "Show me the PTC"
- "What is the gross margin?"
- "Who is the marketer?"

**out_of_scope** - User asks general knowledge questions completely unrelated to business/projects.
Examples: "What is Python?", "How does AI work?", "What is the weather?", "Tell me a joke", "Who is the president?", "Explain quantum physics"

CRITICAL RULES:
1. Respond with ONLY "help", "business_query", "out_of_scope", or "session_restart"
2. NO explanations, NO descriptions, NO extra words
3. SHORT FOLLOW-UP QUESTIONS like "who is the EPO?", "what is the margin?", "what about revenue?" are ALWAYS business_query
4. Questions with pronouns like "it", "them", "this", "that" referring to previous context are business_query
5. Questions about roles (EPO, PM, PML, marketer), finances (margin, revenue, cost, forecast), or status are business_query
6. When in doubt between business_query and out_of_scope, choose business_query
7. Only classify as out_of_scope if the question is CLEARLY about general knowledge unrelated to business"""

        try:
            logging.info(f"Classifying intent for query: '{user_query}'")
            
            # Use specialized parameters for classification (max_tokens=1 to force single word)
            response = await self.client.chat.completions.create(
                model=self.deployment,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_query}
                ],
                temperature=0,  # Deterministic
                max_tokens=10,  # Limit response to just a few tokens
                top_p=1.0,  # No sampling
                stream=False
            )
            
            raw_response = response.choices[0].message.content
            
            # Clean up the response and normalize
            intent = raw_response.strip().lower()
            
            # Remove any quotes, punctuation, or extra whitespace
            intent = intent.replace('"', '').replace("'", '').replace('.', '').replace(',', '').replace('`', '')
            
            # Log the raw response for debugging
            logging.info(f"Intent classification - Raw LLM response: '{raw_response}'")
            logging.info(f"Intent classification - Cleaned: '{intent}'")
            
            # Extract first word if multiple words returned
            first_word = intent.split()[0] if intent.split() else intent
            
            # Check if response contains our target words (check first word first, with priority order)
            if first_word == "session_restart" or first_word == "session" or "restart" in first_word or "session_restart" in intent:
                logging.info("✓ Classified as SESSION_RESTART intent (from LLM)")
                return "session_restart"
            elif first_word == "help" or "help" in first_word:
                logging.info("✓ Classified as HELP intent (from LLM)")
                return "help"
            elif first_word == "out_of_scope" or first_word == "out" or "out_of_scope" in intent:
                logging.info("✓ Classified as OUT_OF_SCOPE intent (from LLM)")
                return "out_of_scope"
            elif first_word in ["business_query", "business", "query"] or "business" in first_word:
                logging.info("✓ Classified as BUSINESS_QUERY intent (from LLM)")
                return "business_query"
            else:
                # If LLM response is unclear, use keyword-based fallback
                logging.warning(f"⚠ LLM returned unclear response: '{raw_response}'")
                query_lower = user_query.lower()
                
                # Check for session restart keywords FIRST (highest priority)
                session_restart_keywords = ['clear', 'start new', 'new chat', 'restart', 'reset', 
                                           'start over', 'begin again', 'fresh start', 'clear history', 
                                           'new session', 'start fresh', 'new conversation']
                
                # Check for help keywords
                help_keywords = ['help', 'what can you', 'how do i use', 'what do you do', 'guide me', 
                                'what is this bot', 'capabilities', 'how to use this', 'usage guide', 
                                'instructions', 'what are your capabilities']
                
                # Check for NPD/TD/IPD business keywords - EXPANDED LIST
                business_keywords = [
                    # Project types
                    'npd', 'td', 'ipd', 'pd', 'project', 'program', 'projects', 'programs',
                    # Roles
                    'epo', 'pm', 'pml', 'marketer', 'manager', 'owner', 'lead',
                    'engr', 'engineer', 'who is', 'who are', 'assigned',
                    # Financial terms
                    'margin', 'revenue', 'cost', 'forecast', 'backlog', 'consumption',
                    'financial', 'gross margin', 'gm', 'npv', 'irr', 'roi', 'asp',
                    'budget', 'investment', 'nre',
                    # Gates and milestones
                    'milestone', 'gate', 'pc', 'dc', 'dr', 'qc', 'mr', 'vc', 'fsp', 'fpr',
                    'plan commit', 'design release', 'qualify complete', 'manufacturing release',
                    'tapeout', 'schedule', 'status', 'phase', 'current phase',
                    # Project identifiers (patterns)
                    'n07', 'n08', 'n09', 'n06', 'n05', 'n04', 'n0',
                    # Organizational
                    'psg', 'amg', 'isg', 'division', 'group', 'business unit', 'bu',
                    'pmd', 'ipd', 'sid', 'asd', 'apd', 'mpd', 'isd', 'icd',
                    # Products and customers
                    'customer', 'customers', 'driving customer', 'corporation', 'opn', 'product',
                    # PTC related
                    'ptc', 'original schedule', 'current schedule', 'os', 'cs',
                    # Follow-up indicators (pronouns and references)
                    'it', 'them', 'this', 'that', 'those', 'these', 'the project',
                    'what about', 'tell me more', 'show me', 'list', 'how many', 'which',
                    'what is the', 'what are the', 'who is the', 'who are the'
                ]
                
                # Priority order: session_restart > help > business_query > out_of_scope
                if any(keyword in query_lower for keyword in session_restart_keywords):
                    logging.info(f"✓ Classified as SESSION_RESTART intent (keyword fallback)")
                    return "session_restart"
                elif any(keyword in query_lower for keyword in help_keywords):
                    logging.info(f"✓ Classified as HELP intent (keyword fallback)")
                    return "help"
                elif any(keyword in query_lower for keyword in business_keywords):
                    logging.info(f"✓ Classified as BUSINESS_QUERY intent (keyword fallback)")
                    return "business_query"
                else:
                    # Default to business_query for short queries (likely follow-ups)
                    # Only classify as out_of_scope for longer, clearly unrelated queries
                    if len(user_query.split()) <= 6:
                        logging.info(f"✓ Classified as BUSINESS_QUERY intent (short query - likely follow-up)")
                        return "business_query"
                    else:
                        logging.info(f"✓ Classified as OUT_OF_SCOPE intent (keyword fallback - no match)")
                        return "out_of_scope"
                
        except Exception as e:
            logging.error(f"✗ Error classifying intent: {str(e)}")
            # On error, try keyword-based fallback before defaulting
            try:
                query_lower = user_query.lower()
                
                # Check for session restart keywords FIRST
                session_restart_keywords = ['clear', 'start new', 'new chat', 'restart', 'reset', 
                                           'start over', 'begin again', 'fresh start', 'clear history', 
                                           'new session', 'start fresh', 'new conversation']
                
                # Check for help keywords
                help_keywords = ['help', 'what can you', 'how do i use', 'what do you do', 'guide me', 
                                'what is this bot', 'capabilities', 'how to use this', 'usage guide']
                
                # Check for NPD/TD/IPD business keywords - EXPANDED LIST
                business_keywords = [
                    'npd', 'td', 'ipd', 'pd', 'project', 'program', 'epo', 'pm', 'pml', 
                    'margin', 'revenue', 'cost', 'forecast', 'milestone', 'gate', 'customer',
                    'n07', 'n08', 'n09', 'n06', 'n05', 'psg', 'amg', 'isg', 'division',
                    'ptc', 'schedule', 'status', 'who is', 'who are', 'what is the', 'what are the',
                    'it', 'them', 'this', 'that', 'those', 'what about', 'tell me more', 'show me'
                ]
                
                if any(keyword in query_lower for keyword in session_restart_keywords):
                    logging.info(f"✓ Classified as SESSION_RESTART intent (error fallback)")
                    return "session_restart"
                elif any(keyword in query_lower for keyword in help_keywords):
                    logging.info(f"✓ Classified as HELP intent (error fallback)")
                    return "help"
                elif any(keyword in query_lower for keyword in business_keywords):
                    logging.info(f"✓ Classified as BUSINESS_QUERY intent (error fallback)")
                    return "business_query"
                else:
                    # Default to business_query for short queries (likely follow-ups)
                    if len(user_query.split()) <= 6:
                        logging.info(f"✓ Classified as BUSINESS_QUERY intent (error fallback - short query)")
                        return "business_query"
                    else:
                        logging.info(f"✓ Classified as OUT_OF_SCOPE intent (error fallback - no match)")
                        return "out_of_scope"
            except:
                pass
            
            # Final fallback - default to business_query for short queries, out_of_scope for longer ones
            if len(user_query.split()) <= 6:
                logging.warning(f"⚠ Final fallback: Defaulting to BUSINESS_QUERY (short query)")
                return "business_query"
            else:
                logging.warning(f"⚠ Final fallback: Defaulting to OUT_OF_SCOPE")
                return "out_of_scope"

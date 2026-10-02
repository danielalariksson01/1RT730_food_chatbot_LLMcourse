import gradio as gr
from collections import defaultdict
from google import genai
from pathlib import Path
import json
import psycopg2

client = genai.Client()
default_model = "gemini-3.8-flash"

if "demo" in locals() and demo.is_running:
    demo.close()

chats = defaultdict(lambda: None)

def chat(inputs, history, request: gr.Request):
    
    #tillåt bara text men om de skickar bild så ska det inte krasha
    text_from_input = inputs.get('text')
    #image_from_input = inputs.get('files')
    
    #behåll
    message = [{"role": "user", "content": text_from_input}] + (history or [])
    
    #behåll
    message_text = "\n".join(f"{m['role']}: {m['content']}" for m in message if isinstance(m.get("content"), str))
    
    #denna ska inte finnas
    r""" if image_from_input:
        file_obj = image_from_input[0]
        file_path = getattr(file_obj, "name", None) or (file_obj if isinstance(file_obj, str) else None)
        if not file_path or not Path(file_path).exists():
            yield "Kunde inte hitta filväg: " + str(file_path)
            return

        uploaded_file = client.files.upload(file=Path(file_path))

        system_instruction = (
            'You are an expert in mushrooms and you have to provide information about the mushroom from the picture attached. Return exactly one JSON object and no additional information. Format: { "common_name": "Inkcap", "genus": "Coprinus", "confidence": 0.5, "visible": ["cap", "hymenium", "stipe"], "color": "orange", "edible": true }'
        )

        result = client.models.generate_content(
            model=default_model,
            contents=[uploaded_file, "\n\n", system_instruction],
        )

        mushroom_json_text = getattr(result, "text", None) or (getattr(result, "output_text", None) if hasattr(result, "output_text") else str(result))
        print("JSON:", mushroom_json_text)
        chats[request.session_hash] = mushroom_json_text """
    
    #denna ska inte finnas
    r""" elif chats[request.session_hash] == None:
        yield "Send a picture of a mushroom"
        return """
     
    #denna ska finnas, ändra system_instruction och lägg till själva RAG systemet   
    #lägga till allergier
    #användaren måste på något sätt i prompten säga hur många recept man vill ha och annars använda standard mått. Men en LLM får prompten som input och sedan ska en annan skriva JSON, för att sedan göra embedding på dem orden, hitta recept och sedan ska en LLM bygga själva recepten men hjälp av produkterna.
    #punish recept som har något med deras allergi i och gör produkter som innehåller ingredienser som de redan har i sitt kök mer attraktiva.
    if message:
        #gör embedding på message och sedan använd för att göra en vector sökning i databasen och hämta de 5 mest relevanta recepten. Använd sedan dessa recept som kontext i system_instruction.
        json_recipes = client.interactions.create(
            model=default_model,
            system_instruction="You are a recipe assistant. You will be given instructions on what the person wants to eat and you need to structure the information in the following JSON format: {recipe 1: ingrediens, ...} where the ingrediens is a string with all ingrediens listed, if the user says 4 recipes but only provides what ingrediens they want the firs to contain, you have to decide key ingredient like chicken etc for the rest. If they do not provide a number of recipes, give them 7 recipes. If they provide any dietary restrictions you must put them in the JSON as diet. If they put any ingredients they want to use but not for a particular recipe, you must also put that in the JSON file as owned products.",
            input=[{"type": "text", "text": message_text},
                   {"type": "text", "text": chats[request.session_hash]}],
        )
        
        #hitta ett recept för varje recipe som finns i json filen och gör embedding på dem och använd dessa embeddings för att göra en vector sökning i databasen och hämta de 5 mest relevanta recepten. Använd sedan dessa recept som kontext i system_instruction.
        json_text = json_recipes.output_text
        recipes = json.loads(json_text)
        recipes_chosen = {}
        for key, value in recipes.items():
            ingredients = value.get("ingredients", [])
            diet = value.get("diet", "")
            owned_products = value.get("owned_products", [])
            embedded_ingredients = client.models.embed_content(
                model="gemini-embedding-001",
                contents=ingredients
            )
            embedded_vector = embedded_ingredients.embeddings[0].values
            #gör embedding på ingredienserna och använd dessa embeddings för att göra en vector sökning i databasen och hämta de 5 mest relevanta recepten. Använd sedan dessa recept som kontext i system_instruction.
            #hämta de 5 mest relevanta recepten från databasen
            conn= psycopg2.connect(
                dbname="recepies",
                user="food",
                password="food",
                host="db"
            )
            cur = conn.cursor()
            cur.execute("SELECT title, ingredients FROM recipes WHERE ingredients LIKE %s LIMIT 5;", (f"%{ingredients[0]}%",))
            relevant_recipes = cur.fetchall()
            scored_matches = []
            for recipe_id, title, ingredients in relevant_recipes:
                score = 0
                for ingredient in ingredients:
                    if ingredient in diet:
                        score -= 1
                    elif ingredient in owned_products:
                        score += 0.2
                scored_matches.append((score, title, ingredients))
            scored_matches.sort(reverse=True)
            
           #i denna delen ska vi sedan lägga in att den väljer utifrån produkter i svenska mataffärer
            
            
            

            #gör per recept och sedan lägg i en lista och sedan ta en annan modell som bara sammanställer detta, men vill egentligen ha en prompt per recept.
            #vad händer om alla recept man får innehåller saker som man är allergisk mot?
        result = client.models.embed_content(
                model="gemini-embedding-001",
                contents=message_text)
        
        interaction = client.interactions.create(
            model=default_model,
            system_instruction="Use the JSON info to answer the question and if there is no question, summarize the information about the mushroom. Also add if the mushroom is poisonous, explain whether it could be safe to eat in any state or preperation and desribe the conditions under which it might be edible.", 
                 input=[{"type": "text", "text": message_text},
                     {"type": "text", "text": chats[request.session_hash]}],
            stream=True
        )
        
        #den ska fortfarande göra stream
        full_response=""
        for event in interaction:
            if event.event_type=="step.delta":
                if event.delta.type == "text":
                    full_response += event.delta.text
                    yield full_response
    
    #else borde inte behövas finnas eftersom de måste ha något i prompten
    r""" else:
        interaction = client.interactions.create(
            model=default_model,
            system_instruction="Summarize information about the mushroom in a written out paragraph. Also add if the mushroom is poisonous, explain whether it could be safe to eat in any state or preperation and desribe the conditions under which it might be edible.",
            input={"type": "text", "text": chats[request.session_hash]},
            stream=True
        )
        full_response=""
        for event in interaction:
            if event.event_type=="step.delta":
                if event.delta.type =="text":
                    full_response += event.delta.text
                    yield full_response
    return """
        
        
demo = gr.ChatInterface(fn=chat, multimodal=True)
demo.launch()
import gradio as gr
from collections import defaultdict
from google import genai
from pathlib import Path

client = genai.Client()
default_model = "gemini-3.8-flash"

if "demo" in locals() and demo.is_running:
    demo.close()

chats = defaultdict(lambda: None)

def chat(inputs, history, request: gr.Request):
    
    text_from_input = inputs.get('text')
    image_from_input = inputs.get('files')
    
    message = [{"role": "user", "content": text_from_input}] + (history or [])
    
    message_text = "\n".join(f"{m['role']}: {m['content']}" for m in message if isinstance(m.get("content"), str))
    
    if image_from_input:
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
        chats[request.session_hash] = mushroom_json_text
        
    elif chats[request.session_hash] == None:
        yield "Send a picture of a mushroom"
        return
        
    if message:
        interaction = client.interactions.create(
            model=default_model,
            system_instruction="Use the JSON info to answer the question and if there is no question, summarize the information about the mushroom. Also add if the mushroom is poisonous, explain whether it could be safe to eat in any state or preperation and desribe the conditions under which it might be edible.", 
                 input=[{"type": "text", "text": message_text},
                     {"type": "text", "text": chats[request.session_hash]}],
            stream=True
        )
        full_response=""
        for event in interaction:
            if event.event_type=="step.delta":
                if event.delta.type == "text":
                    full_response += event.delta.text
                    yield full_response
    else:
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
    return
        
        
demo = gr.ChatInterface(fn=chat, multimodal=True)
demo.launch()
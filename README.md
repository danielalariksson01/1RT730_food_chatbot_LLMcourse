To start project:
- docker compose down
- docker compose up
- docker compose exec db psql -U food -d recipes -c "DROP TABLE IF EXISTS recipes;"
- Get-Content .\schema.sql | docker compose exec -T -i db psql -U food -d recipes
- docker compose exec jupyter bash
- python Food_chatbot.py

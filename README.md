# To start project:
docker compose down
docker compose up
docker compose exec db psql -U food -d recipes -c "DROP TABLE IF EXISTS recipes;"
docker compose exec db psql -U food -d recipes -c "DROP TABLE IF EXISTS ingredients;"

# IF no Database exits
Get-Content .\schema.sql | docker compose exec -T -i db psql -U food -d recipes
docker compose exec jupyter python /home/jovyan/work/create_datafiles.py

# When the database exists
docker compose exec jupyter python /home/jovyan/work/Food_chatbot.py


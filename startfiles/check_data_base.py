import psycopg2

conn= psycopg2.connect(
    dbname="recepies",
    user="food",
    password="food",
    host="db"
)

cur = conn.cursor()
cur.execute("SELECT * FROM recipes")
print(cur.fetchone())

cur.execute("SELECT id, title FROM recipes LIMIT 5;")
for row in cur.fetchall():
    print(row)
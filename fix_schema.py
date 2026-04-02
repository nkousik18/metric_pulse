import redshift_connector
from dotenv import load_dotenv
import os

load_dotenv()

conn = redshift_connector.connect(
    host=os.getenv('REDSHIFT_HOST'),
    port=int(os.getenv('REDSHIFT_PORT', 5439)),
    database=os.getenv('REDSHIFT_DATABASE'),
    user=os.getenv('REDSHIFT_USER'),
    password=os.getenv('REDSHIFT_PASSWORD')
)

cursor = conn.cursor()

# Check existing schemas
cursor.execute("SELECT schema_name FROM information_schema.schemata;")
schemas = cursor.fetchall()
print("Existing schemas:")
for s in schemas:
    print(f"  - {s[0]}")

# Create schemas explicitly
print("\nCreating schemas...")
for schema in ['raw_data', 'staging', 'marts']:
    try:
        cursor.execute(f"CREATE SCHEMA {schema};")
        conn.commit()
        print(f"  ✓ Created {schema}")
    except Exception as e:
        if "already exists" in str(e):
            print(f"  - {schema} already exists")
        else:
            print(f"  ✗ {schema}: {e}")
        conn.rollback()

# Verify
cursor.execute("SELECT schema_name FROM information_schema.schemata;")
schemas = cursor.fetchall()
print("\nSchemas after creation:")
for s in schemas:
    print(f"  - {s[0]}")

cursor.close()
conn.close()

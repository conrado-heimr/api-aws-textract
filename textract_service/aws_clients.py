import boto3

# Configurações do AWS S3 e Textract
# ATENÇÃO: Substitua 'YOUR_S3_BUCKET_NAME' pelo nome do seu bucket S3.
# Certifique-se de que as credenciais AWS estão configuradas no ambiente
# (variáveis de ambiente, ~/.aws/credentials, etc.)
AWS_REGION = "us-east-1"
S3_BUCKET_NAME = "teste-textract-conrado" 

# Inicializa os clientes AWS para Textract e S3
# Estes clientes serão usados em toda a aplicação
session = boto3.Session()
textract_client = session.client('textract', region_name=AWS_REGION)
s3_client = session.client('s3', region_name=AWS_REGION)

# Para uso em outros módulos
__all__ = ['textract_client', 's3_client', 'S3_BUCKET_NAME']


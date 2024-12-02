# Kafka Video Processing Microservice

## Overview
A robust, scalable microservice for processing videos using Apache Kafka and AWS MSK.

## Prerequisites
- Python 3.10+
- AWS Account
- Access to AWS MSK Cluster
- AWS IAM Credentials

## Setup Instructions

### 1. Clone the Repository
```bash
git clone https://your-repo-url/kafka-video-processor.git
cd kafka-video-processor
```

### 2. Create Virtual Environment
```bash
python -m venv venv
source venv/bin/activate  # On Windows use `venv\Scripts\activate`
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Configure AWS Credentials
Option 1: AWS CLI Configuration
```bash
aws configure
```

Option 2: Environment Variables
```bash
export AWS_ACCESS_KEY_ID=your-access-key
export AWS_SECRET_ACCESS_KEY=your-secret-key
export AWS_REGION=us-east-1
```

### 5. Configure Application
1. Copy `.env` to `.env`
2. Edit `.env` with your specific configurations
```bash
cp .env.example .env
nano .env  # or use your preferred text editor
```

### 6. Running the Application

#### Development Mode
```bash
uvicorn src.main:app --reload --host 0.0.0.0 --port 8000
```

#### Production Deployment
```bash
# Using Gunicorn (recommended for production)
gunicorn -w 4 -k uvicorn.workers.UvicornWorker src.main:app
```

### 7. Health Check
Access the health check endpoint:
```
http://localhost:8000/health
```

## Monitoring and Logging
- Check application logs for detailed tracking
- Use the `/health` endpoint for service status
- Implement additional monitoring as needed

## Troubleshooting
- Ensure AWS credentials are correctly configured
- Verify MSK cluster network accessibility
- Check Kafka topic configurations

## Security Considerations
- Use AWS IAM roles
- Implement network security groups
- Rotate credentials regularly

## Contributing
1. Fork the repository
2. Create your feature branch
3. Commit your changes
4. Push to the branch
5. Create a Pull Request
```

Additional notes for AWS MSK deployment:

1. Ensure your AWS IAM role has necessary Kafka permissions
2. Configure security groups to allow traffic
3. Use AWS Secrets Manager for credential management in production

Would you like me to elaborate on any specific aspect of AWS MSK integration or deployment?

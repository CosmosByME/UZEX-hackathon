FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# data/ must contain the CSV files; the database is built at image build time
RUN python loader.py
CMD ["python", "bot.py"]

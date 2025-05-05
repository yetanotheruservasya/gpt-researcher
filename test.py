import requests

# URL вашего API
url = "http://localhost:8000/report/"

# Данные для отправки запроса
payload = {
    "task": "Research quantum computing",
    "report_type": "summary",
    "report_source": "web",
    "tone": "Objective",
    "headers": {},
    "repo_name": "example-repo",
    "branch_name": "main",
    "generate_in_background": False
}

# Заголовки запроса
headers = {
    "Content-Type": "application/json"
}

# Отправка POST-запроса
try:
    response = requests.post(url, json=payload, headers=headers)
    response.raise_for_status()  # Проверка на ошибки HTTP
    print("Response:", response.json())  # Вывод ответа в формате JSON
except requests.exceptions.RequestException as e:
    print("An error occurred:", e)
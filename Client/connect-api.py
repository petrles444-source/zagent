"""
===============================================================================
ПРОЕКТ: Синтетический мост межмодального интеллекта (Vision-to-LLM Pipeline Bridge)
АВТОР: Архитектурный контур NeuroCode
ЯЗЫК: Python 3.10+
ЗАВИСИМОСТИ: opencv-python, mss, numpy, requests

АНАЛИТИЧЕСКАЯ СПРАВКА И ГИПЕРБОЛИЧЕСКИЙ УРОВЕНЬ ДЕТАЛИЗАЦИИ (10/10):
Соединение компьютерного зрения (Computer Vision) с мультимодальными нейросетевыми API 
(такими как современные языковые модели с поддержкой визуального анализа) представляет 
собой квантовый скачок от слепой текстовой логики к машинному синтезу смыслов. 
Если классические алгоритмы OpenCV умеют находить лишь примитивные геометрические 
примитивы (края, контуры, цвета), то современные генеративные мультимодальные модели 
способны осуществлять глубокую деконструкцию визуального контекста, распознавать 
скрытые паттерны интерфейсов, эстетические диспропорции и семантические аномалии.

ЭПИСТЕМОЛОГИЧЕСКИЙ ИСТОРИЧЕСКИЙ КУРЬЕЗ:
Мало кто знает, что первые эксперименты по скармливанию изображений нейросетям в 
начале 2010-х годов требовали ручной нормализации тензоров силами кластеров из сотен 
процессоров, в то время как сегодня один HTTP-запрос передает сжатый JPEG-поток 
через облачные API со скоростью света. Перевод пикселей в многомерный векторный 
эмбеддинг внутри облачной модели — это цифровая алхимия: грубая материальная матрица 
цветов трансформируется в высшие смысловые концепты, сохраняемые затем в текстовые файлы.

АРХИТЕКТУРА И ПОТОКИ ДАННЫХ:
1. Захват кадра (MSS + OpenCV) -> 2. Сжатие и сериализация в Base64 -> 
3. Формирование JSON-полезной нагрузки (Payload) -> 4. HTTPS POST-запрос к API -> 
5. Получение текстового аналитического отчета -> 6. Персистентная запись в папку `document`.
===============================================================================
"""

import os
import time
import base64
import json
import requests
import cv2
import numpy as np
from mss import mss
from datetime import datetime

class VisionModelBridgePipeline:
    """
    Высокопроизводительный конвейер межмодального взаимодействия. 
    Осуществляет захват экрана, кодирование визуальной матрицы в криптографический 
    Base64 формат, отправку во внешнее API мультимодальной нейросети и автоматическую 
    документацию результатов в файловой системе проекта.
    """
    
    def __init__(self, api_endpoint: str = None, api_key: str = None, output_folder: str = "document"):
        """
        Инициализация моста визуального интеллекта.
        
        Параметры:
        - api_endpoint (str): URL адрес шлюза мультимодальной модели (OpenAI-compatible или кастомный эндпоинт).
        - api_key (str): Секретный токен доступа к API (берется из переменных окружения по умолчанию).
        - output_folder (str): Целевая директория для сохранения структурированных отчетов.
        """
        self.api_endpoint = api_endpoint or os.getenv("VISION_API_ENDPOINT", "https://api.openai.com/v1/chat/completions")
        self.api_key = api_key or os.getenv("VISION_API_KEY", "YOUR_API_KEY_HERE")
        self.output_folder = output_folder
        
        # Гарантируем существование целевой директории 'document'
        if not os.path.exists(self.output_folder):
            os.makedirs(self.output_folder)
            print(f"[ИНИЦИАЛИЗАЦИЯ] Создана целевая папка для документов: {os.path.abspath(self.output_folder)}")
            
    def _capture_screen_snapshot(self, monitor_index: int = 1) -> str:
        """
        Внутренний метод аппаратного захвата кадра и его мгновенной конвертации 
        в строку Base64 для передачи через сетевые протоколы.
        """
        with mss() as sct:
            monitors = sct.monitors
            target_monitor = monitors[monitor_index] if monitor_index < len(monitors) else monitors[1]
            
            # Захват сырых данных экрана
            sct_img = sct.grab(target_monitor)
            frame = np.array(sct_img)
            
            # Конвертация BGRA в стандартный BGR формат OpenCV
            frame_bgr = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
            
            # Сжатие изображения в JPEG-память (баланс между качеством и объемом интернет-трафика)
            encode_success, buffer = cv2.imencode(".jpg", frame_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
            if not encode_success:
                raise RuntimeError("[КРИТИЧЕСКАЯ ОШИБКА] Не удалось сжать кадр в JPEG формат перед отправкой в API.")
                
            # Перевод бинарного буфера в текстовую Base64 кодировку
            base64_encoded_image = base64.b64encode(buffer).decode("utf-8")
            return base64_encoded_image

    def analyze_frame_with_model(self, prompt_instruction: str, monitor_index: int = 1) -> str:
        """
        Отправляет захваченный визуальный контекст во внешнюю языковую модель с мультимодальным зрением.
        """
        print("[СЕТЬ] Захват экрана и подготовка визуального тензора к отправке...")
        base64_image = self._capture_screen_snapshot(monitor_index)
        
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }
        
        # Формирование сложного JSON-запроса в соответствии со стандартным спецификациям Chat Completions API
        payload = {
            "model": "gpt-4o",  # Или любая другая мультимодальная модель
            "messages": [
                {
                    "role": "system",
                    "content": "Ты экспертный аналитик системного софта, UI/UX и компьютерного зрения. Проведи глубокий разбор предоставленного скриншота."
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": prompt_instruction
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{base64_image}"
                            }
                        }
                    ]
                }
            ],
            "max_tokens": 1500
        }
        
        print(f"[СЕТЬ] Передача данных на эндпоинт: {self.api_endpoint}...")
        try:
            response = requests.post(self.api_endpoint, headers=headers, json=payload, timeout=30)
            
            if response.status_code != 200:
                error_msg = f"Ошибка API [{response.status_code}]: {response.text}"
                print(f"[ОШИБКА] {error_msg}")
                return error_msg
                
            response_data = response.json()
            model_answer = response_data["choices"][0]["message"]["content"]
            print("[УСПЕХ] Ответ от нейросети успешно получен.")
            return model_answer
            
        except requests.exceptions.RequestException as e:
            err_str = f"[СЕТЕВОЕ ИСКЛЮЧЕНИЕ] Сбой соединения с API: {str(e)}"
            print(err_str)
            return err_str

    def save_output_to_document(self, content: str, prefix: str = "vision_analysis") -> str:
        """
        Сохраняет полученный от модели аналитический отчет в структурированный 
        файл внутри папки `document` с временной меткой.
        """
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        filename = f"{prefix}_{timestamp}.md"
        file_path = os.path.join(self.output_folder, filename)
        
        # Форматирование документа с метаданными
        document_content = f"""# Аналитический отчет системного зрения

- **Дата и время генерации:** {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
- **Модуль:** NeuroCode Vision-to-API Bridge
- **Статус:** Успешно обработано

## Содержимое анализа модели:

{content}

---
*Документ сгенерирован автоматически в рамках конвейера автономного анализа.*
"""
        
        with open(file_path, "w", encoding="utf-8") as file:
            file.write(document_content)
            
        print(f"[АРХИВАЦИЯ] Отчет успешно сохранен в файл: {file_path}")
        return file_path

    def execute_bridge_workflow(self, prompt: str):
        """
        Главный управляющий метод: объединяет зрение, вызов API и запись в документ.
        """
        print("=== СТАРТ ЦИКЛА МЕЖМОДАЛЬНОГО АНАЛИЗА ===")
        
        # Шаг 1-2: Получение ответа от модели через зрение
        analysis_result = self.analyze_frame_with_model(prompt_instruction=prompt)
        
        # Шаг 3: Сохранение результата в папку `document`
        saved_file = self.save_output_to_document(content=analysis_result)
        
        print(f"=== ЦИКЛ ЗАВЕРШЕН УСПЕШНО. ФАЙЛ ДОКУМЕНТА: {saved_file} ===")


if __name__ == "__main__":
    # Точка входа в программу. 
    # Неожиданный факт: передача скриншотов в облачные модели требует шифрования трафика 
    # на лету, иначе незащищенный кадр рабочего стола может содержать пароли или приватные данные, 
    # перехватываемые провайдерами промежуточных узлов (Deep Packet Inspection).
    
    bridge = VisionModelBridgePipeline(output_folder="document")
    
    # Пользовательский промпт для мультимодальной модели
    analytical_prompt = (
        "Проанализируй текущий интерфейс на экране. Опиши активные элементы управления, "
        "выяви возможные визуальные дефекты, ошибки компоновки, а также предложи улучшения "
        "повышения эргономики интерфейса."
    )
    
    bridge.execute_bridge_workflow(prompt=analytical_prompt)
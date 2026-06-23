import customtkinter as ctk

# Настройка окна
app = ctk.CTk()
app.geometry("400x300")
app.title("Пример CTkComboBox")

# 1. Функция-обработчик (вызывается при выборе элемента)
def combobox_callback(choice):
    print(f"Пользователь выбрал: {choice}")
    label.configure(text=f"Выбрано: {choice}")

# 2. Функция для получения текущего текста кнопкой
def show_current_value():
    current_text = my_combo.get()
    label.configure(text=f"Текущее значение: {current_text}")

# Список элементов
languages = ["Python", "JavaScript", "C++", "Go"]

# 3. Создание виджета CTkComboBox
my_combo = ctk.CTkComboBox(
    master=app,
    values=languages,
    command=combobox_callback, # Сработает автоматически при выборе
    width=200
)
my_combo.pack(pady=20)

# Установка значения по умолчанию (опционально)
my_combo.set("Python") 

# Вспомогательные виджеты для теста
btn = ctk.CTkButton(app, text="Узнать значение", command=show_current_value)
btn.pack(pady=10)

label = ctk.CTkLabel(app, text="Выведи результат сюда", font=("Arial", 16))
label.pack(pady=20)

app.mainloop()

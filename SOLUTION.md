# Yechim tavsifi (formaga) / Описание решения (для формы)

## O‘zbekcha

**Prototip:** Telegram-bot — o‘rnatish va ro‘yxatdan o‘tishsiz ishlaydi, rus va o‘zbek (lotin va kirill) tillaridagi savollarga savol tilida javob beradi.

**Texnologiyalar:** Python, DuckDB (analitik SQL baza), LLM (Claude) tool-calling agent, aiogram 3, RapidFuzz.

**Usul:**
1. *Ma’lumotlarni tayyorlash.* CSV fayllar bir marta tozalanadi: «78 356 027.52» kabi raqamlar va sanalar to‘g‘ri turga o‘tkaziladi; har bir bitimga shartnoma kartochkasi (valyuta, tovar atributlari, TN VED, guruh), bitim sanasidagi dollar kursi (so‘m va dollardagi summa), sotuvchi/xaridor/broker nomlari, hajm (Количество × Лот) va birlik narxi qo‘shiladi. Viloyat nomlari bir xil yozuvga keltiriladi, bir tovarning turli yozilishlari («1 сорт», «1-сорта») bitta kalitga birlashtiriladi.
2. *Agent.* LLM javobni o‘zi bilmaydi — faqat uchta vosita orqali ma’lumot oladi: faqat o‘qish uchun SQL so‘rov, kompaniyani nom/STIR bo‘yicha qidirish (kirill↔lotin, imlo xatolari), tovarni qidirish. Barcha hisob-kitoblar (summa, o‘rtacha, ulush, reyting) SQL ichida bajariladi.
3. *O‘ylab topishga qarshi himoya.* (a) Qat’iy qoidalar: tashqi bilim taqiqlangan, ma’lumot bo‘lmasa — ochiq «ma’lumotda yo‘q» deyiladi; (b) **avtomatik tekshiruvchi** (LLM emas, oddiy kod): javobdagi har bir raqam va sana vositalar natijalarida borligini tekshiradi, topilmasa agent javobni qayta hisoblashga majbur qilinadi; (c) bekor qilingan bitimlar va turli valyutalar to‘g‘ri hisobga olinadi.
4. *Shaffoflik.* Har bir javob ostida «Asos» bloki: qaysi ma’lumot, filtrlar, davr, taxminlar va aniq SQL so‘rov ko‘rsatiladi — javobni qo‘lda tekshirish mumkin.
5. *Tekshirish.* Javoblar oldindan tayyorlangan savollar to‘plamida (jumladan javobi yo‘q «tuzoq» savollar) qo‘lda yozilgan SQL natijalari bilan solishtirildi; barcha savol-javoblar jurnalga yoziladi. Har bir javob 90 soniyadan oshmasligi uchun vaqt cheklovi bor.

## Русский

**Прототип:** Telegram-бот, работает без установки и регистрации, отвечает на русском и узбекском (латиница и кириллица) на языке вопроса.

**Технологии:** Python, DuckDB (аналитическая SQL-база), ИИ-агент на LLM (Claude) с вызовом инструментов, aiogram 3, RapidFuzz.

**Метод:**
1. *Подготовка данных.* CSV один раз очищаются: суммы вида «78 356 027.52» и даты приводятся к типам; к каждой сделке присоединены карточка контракта (валюта, атрибуты товара, ТН ВЭД, группа), курс доллара на дату сделки (сумма в сумах и долларах), названия продавца/покупателя/брокеров, объём (Количество × Лот) и цена за единицу. Регионы приведены к единому написанию, разные написания одного товара («1 сорт», «1-сорта») объединены одним ключом.
2. *Агент.* LLM не отвечает «из головы» — данные доступны только через три инструмента: SQL-запрос только на чтение, поиск компании по названию/ИНН (кириллица↔латиница, опечатки), поиск товара. Все вычисления (суммы, средние, доли, рейтинги) выполняются в SQL.
3. *Защита от выдумывания.* (а) Жёсткие правила: внешние знания запрещены, если ответа нет — прямо говорится «в данных нет»; (б) **автоматический верификатор** (обычный код, не LLM): каждое число и дата в ответе сверяются с результатами инструментов, при несовпадении агент обязан пересчитать; (в) корректный учёт аннулированных сделок и разных валют.
4. *Прозрачность.* Под каждым ответом — блок «Основание»: какие данные, фильтры, период, допущения и точный SQL-запрос — ответ можно проверить вручную.
5. *Проверка.* Ответы сверены на наборе тестовых вопросов (включая «вопросы-ловушки» без ответа в данных) с результатами SQL, написанного вручную; все вопросы и ответы логируются. Ограничение времени гарантирует ответ быстрее 90 секунд.

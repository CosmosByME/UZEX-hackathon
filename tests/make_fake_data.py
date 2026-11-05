"""Generate a small fake dataset in EXACTLY the hackathon CSV format, to test the pipeline
before (or without) the real data.   python tests/make_fake_data.py  -> tests/fake_data/"""
import csv
import random
from datetime import date, timedelta
from pathlib import Path

random.seed(7)
OUT = Path(__file__).parent / "fake_data"
OUT.mkdir(exist_ok=True)

REG_UZ = ["Toshkent shahri", "Toshkent viloyati", "Samarqand viloyati", "Farg‘ona viloyati", "Jizzax viloyati",
          "Qashqadaryo viloyati", "Navoiy viloyati", "Buxoro viloyati", "Qoraqalpog‘iston Respublikasi"]
REG_RU = {"Toshkent shahri": "г. Ташкент", "Toshkent viloyati": "Ташкентская область", "Samarqand viloyati": "Самаркандская область",
          "Farg‘ona viloyati": "Ферганская область", "Jizzax viloyati": "Джизакская область",
          "Qashqadaryo viloyati": "Кашкадарьинская область", "Navoiy viloyati": "Навоийская область",
          "Buxoro viloyati": "Бухарская область", "Qoraqalpog‘iston Respublikasi": "Республика Каракалпакстан"}
PRODUCTS = [  # name, attrs(variant spellings), hs, group, category, industry, unit, lot, base price
    ("Хлопок-сырец (спот)", ["Сорт 1 сорт Класс 2-класс", "1-сорта 2 класс", "СОРТ 1 СОРТ КЛАСС 2-КЛАСС"], "520100", "Высоколиквидные товары", "Сельхозпродукция", "Сельское хозяйство", "килограмм", 1, 9700),
    ("Аммиачная селитра", ["Марка Б", "Б"], "310230", "Высоколиквидные товары", "Химическая продукция", "Химическая промышленность", "тонна", 1, 2720000),
    ("Лист стальной горячекатаный", ["Марка Ст3сп Размер 3х1250х2500мм"], "720851", "Прочие товары", "Металлопродукция", "Металлургия", "килограмм", 1, 15000),
    ("Цемент", ["Марка М400 Тип ЦЕМ II", "М400"], "252329", "Высоколиквидные товары", "Стройматериалы", "Строительство", "тонна", 20, 850000),
    ("Пшеница продовольственная", ["Класс 3 класс", "3-класса"], "100199", "Высоколиквидные товары", "Сельхозпродукция", "Сельское хозяйство", "тонна", 1, 3100000),
    ("Профиль алюминиевый", ["Размер 21х32мм"], "760421", "Прочие товары", "Металлопродукция", "Металлургия", "килограмм", 1, 54000),
    ("Сахар белый", ["Сорт 1 сорт"], "170199", "Высоколиквидные товары", "Продукты питания", "Пищевая промышленность", "тонна", 1, 11000000),
    ("Пряжа хлопчатобумажная", ["Размер Ne 30/1"], "520512", "Прочие товары", "Текстиль", "Текстильная промышленность", "килограмм", 100, 3.1),
]
NAMES_LAT = ["Pudexiz Plast", "Go‘qe Prokat", "Vaminu Industriya", "Kamol Agro", "Orzu Textile", "Baraka Savdo",
             "Nur Metall", "Zarafshon Kimyo", "Sharq Sement", "Oltin Don"]
NAMES_CYR = ["ҲАРАЙЎМ КИМЁ", "ТОШКЕНТ ҚУРИЛИШ", "САМАРҚАНД ДОН", "ФАРҒОНА ТЕКС", "БУХОРО САВДО"]


def fmt(x, dec=2):
    s = f"{x:,.{dec}f}".replace(",", " ")
    return s


def d2s(d):
    return d.strftime("%d.%m.%Y") if d else ""


participants = []
used = set()
for i in range(300):
    inn = str(random.randint(900000000, 999999999))
    if inn in used:
        continue
    used.add(inn)
    if i < len(NAMES_LAT):
        nm = f'"{NAMES_LAT[i]}" MChJ'
    elif i < len(NAMES_LAT) + len(NAMES_CYR):
        nm = f'"{NAMES_CYR[i - len(NAMES_LAT)]}" МЧЖ'
    else:
        nm = random.choice([f'"Firma {i}" MChJ', f"KORXONA {i} MAS’ULIYATI CHEKLANGAN JAMIYATI", f'"ФИРМА {i}" МЧЖ'])
    role = "Продавец" if i < 60 else "Покупатель"
    participants.append((inn, nm, random.choice(REG_UZ), "Торговая компания", role, random.choice(["Да", "Нет"])))
sellers = [p for p in participants if p[4] == "Продавец"]
buyers = [p for p in participants if p[4] == "Покупатель"]

brokers = [(f"BK{i:03d}", f"BROKER {i} MCHJ" if i % 2 else f'"БРОКЕР {i}" МЧЖ', str(random.randint(900000000, 999999999)), random.choice(REG_UZ)) for i in range(1, 21)]

start, end = date(2022, 1, 1), date(2026, 10, 30)
rates = []
r, d = 10829.1, start
while d <= end:
    rates.append((d, round(r, 2)))
    r *= 1 + random.uniform(-0.002, 0.0025)
    d += timedelta(days=1)
rate_of = dict(rates)

contracts = []
cid = 100001
for k in range(220):
    p = random.choice(PRODUCTS)
    s = random.choice(sellers)
    exp = p[0] in ("Пряжа хлопчатобумажная",) or random.random() < 0.05
    reg = d2s(start + timedelta(days=random.randint(0, 1700)))
    contracts.append(dict(id=cid, p=p, attr=random.choice(p[1]), seller=s, export=exp,
                          form=random.choice(["Спот", "Спот", "Спот", "Форвард", "Фьючерс"]),
                          tt=random.choice(["Английский аукцион", "Двусторонний аукцион", "Обратный аукцион"]),
                          region=s[2], pay=random.choice([3, 5, 10]), deliv=random.choice([7, 10, 19]), reg=reg))
    cid += 1

with open(OUT / "contracts.csv", "w", encoding="utf-8", newline="") as f:
    w = csv.writer(f)
    w.writerow("Номер контракта,Наименование продукта,Марка товара,Размер товара,Сорт товара,Тип товара,Класс товара,Код ТН ВЭД,Группа товара,Категория товара,Отрасль промышленности,Единица измерения,Лот,Валюта,Базисная цена,Сумма залога,Базиспоставки,Регион,Адрес склада,Тип торгов,Тип контракта,Форма контракта,Срок оплаты,Срок поставки,Упаковка,ИНН продавца,Дата регистрации,Действует до".split(","))
    for c in contracts:
        p = c["p"]
        price = p[8] if not c["export"] else round(p[8] / 11000, 4) if p[8] > 100 else p[8]
        w.writerow([c["id"], p[0], "", "", "", "", "", p[2], p[3], p[4], p[5], p[6], p[7],
                    "Доллар США" if c["export"] else "Узбекский сум", price, "10 %", "EXW", REG_RU[c["region"]],
                    f'{c["seller"][1]} STIR: {c["seller"][0]}, ko‘chasi 1-uy', c["tt"],
                    "Экспортный" if c["export"] else "Внутренний", c["form"], c["pay"], c["deliv"], "навалом",
                    c["seller"][0], c["reg"], "31.12.2026"])

STAT = ["Исполнен"] * 10 + ["Исполнен(Частично)", "Аннулирован(Не оплачен)", "Аннулирован(Не оплачен)", "Оплачен"]
deals_by_year = {}
num = 400000
d = date(2022, 1, 3)
while d <= end:
    if d.weekday() < 5:
        for _ in range(random.randint(5, 15)):
            num += random.choice([1, 1, 1, 2])
            c = random.choice(contracts)
            p = c["p"]
            qty = random.randint(1, 500) if p[6] == "тонна" else random.randint(100, 120000)
            if p[7] == 100:
                qty = random.randint(1, 300)
            base = p[8] / 11000 if c["export"] and p[8] > 100 else p[8]
            sp = base * random.uniform(0.9, 1.1)
            price = sp * random.uniform(0.98, 1.15)
            amount = qty * p[7] * price
            st = random.choice(STAT) if d < date(2026, 10, 20) else random.choice(["Ждёт оплату", "Не подписан", "Заключен"])
            if d == end:
                st = "Новый"
            pay = d + timedelta(days=random.randint(1, c["pay"])) if st in ("Исполнен", "Исполнен(Частично)", "Оплачен") else None
            dl = pay + timedelta(days=random.randint(1, c["deliv"])) if pay and st.startswith("Исполнен") else None
            delivered = qty if st == "Исполнен" else (qty // 2 if st == "Исполнен(Частично)" else 0)
            row = [num, d2s(d), f"{random.randint(10, 16)}:{random.randint(0, 59):02d}:{random.randint(0, 59):02d}", c["tt"],
                   qty, fmt(amount), fmt(sp), c["id"], f'{p[0]} {c["attr"]}', p[7], p[6], c["region"],
                   "Экспортный" if c["export"] else "Внутренний", c["form"], st, c["seller"][0],
                   random.choice(buyers)[0], random.choice(brokers)[0], random.choice(brokers)[0], d2s(pay), d2s(dl), delivered]
            deals_by_year.setdefault(d.year, []).append(row)
    d += timedelta(days=1)

H = "Номер сделки,Дата сделки,Время сделки,Тип торгов,Количество,Сумма сделки,Стартовая цена,Номер контракта,Наименование товара,Лот,Единица измерения,Регион,Тип контракта,Форма контракта,Состояние сделки,ИНН продавца,ИНН покупателя,Брокер продавца,Брокер покупателя,Дата оплаты,Дата поставки,Поставлено".split(",")
for y, rows in deals_by_year.items():
    rows.sort(key=lambda r: (r[0]))
    with open(OUT / f"deals_{y}.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(H)
        w.writerows(rows)

for name, header, rows in [
    ("participants.csv", "ИНН,Наименование,Регион,Вид деятельности,Роль,Плательщик НДС", participants),
    ("brokers.csv", "Код брокера,Наименование,ИНН,Регион", brokers),
    ("usd_rates.csv", "Дата,Курс", [(d2s(a), b) for a, b in rates]),
]:
    with open(OUT / name, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(header.split(","))
        w.writerows(rows)
print("fake data written to", OUT, {y: len(r) for y, r in deals_by_year.items()})

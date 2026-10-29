# ЕЭСБО QR → ZKTeco C3-200 turniket integratsiyasi

## Muhim: nega o'rtada kompyuter kerak

C3-200 panel QR-koddagi matnni ЕЭСБО serveriga o'zi yubora olmaydi va QR o'quvchi uni
**Wiegand** orqali panelga ulansa, chekdagi `&ticket_id=GUID` matni 26/34 bitli "karta raqami"ga
aylanib qoladi — biletni tekshirib bo'lmaydi. Shuning uchun sxema shunday:

```
 Chek (QR)
    │
 QR50BM ──RS485 (3:485+, 4:485-)──► USB-RS485 adapter ──► Mini-PC / kompyuter (shu skript)
                                                                │  HTTPS
                                                                ├──► ЕЭСБО API: ValidateTicketAsync
                                                                │  TCP 4370 (LAN)
                                                                └──► C3-200  192.168.1.201
                                                                        LOCK1 rele ──► turniket
```

Kompyuter va panel bitta tarmoqda bo'lishi va kompyuterda internet bo'lishi kerak.

## Ulanish (sim)

**QR50BM (orqa klemma):**
| QR50BM | Qayerga |
|---|---|
| 1 VCC | 12V blok + (yoki C3 `READER +12V`) |
| 2 GND | 12V blok − va USB-RS485 adapter GND |
| 3 485+ | USB-RS485 adapter A (D+) |
| 4 485− | USB-RS485 adapter B (D−) |
| 5 WG0 / 6 WG1 | ulanmaydi |

**C3-200 → turniket:** `LOCK1` klemmasi (`COM` va `NO`) turniketning "ochish / button / dry contact"
kirishiga. Turniket boshqaruv platasida bu odatda `OPEN-A` / `IN1` + `COM` deb yoziladi
(bir yo'nalish uchun). Panelni o'zini `+12V/GND` (POWER) orqali quvvatlang.

> QR50BM'da RS485 va Wiegand chiqishi zavodda tanlanadi (yorliqda "Optional" katakchalar).
> RS485 belgilanmagan bo'lsa, sotuvchidan RS485/USB versiya so'rang yoki USB versiyasini to'g'ridan-to'g'ri kompyuterga ulang (unda u COM-port bo'lib ko'rinadi — `serial_port` ga shuni yozing).

## O'rnatish

1. Python 3.10+ o'rnating.
2. Papkada:
   ```
   pip install -r requirements.txt
   copy config.example.ini config.ini      (Linux: cp)
   ```
3. `config.ini` ni to'ldiring: `base_url`, `login`, `password`, `serial_port`.

## Bosqichma-bosqich tekshirish

1. **Panel:** `python turnstile_gateway.py --test-open` → turniket 5 soniya ochilishi kerak.
   Ulanmasa: `ping 192.168.1.201`, ZKAccess dasturini yoping (u bir vaqtda ulanib turgan bo'lsa
   panel boshqa ulanishni rad etishi mumkin), Communication password'ni tekshiring.
2. **ЕЭСБО:** `python turnstile_gateway.py --test-api` → GetMe javobi chiqadi.
3. **Biletsiz sinov:** `python turnstile_gateway.py --stdin` va QR matnini kiriting
   (masalan `&ticket_id=...`). To'langan bilet → "BILET QABUL QILINDI" + turniket ochiladi.
4. **To'liq ish:** `python turnstile_gateway.py` — chekni o'quvchiga tuting.

Barcha hodisalar `gateway.log` faylida.

## Avtomatik ishga tushirish

**Windows:** Task Scheduler → "At startup" → `pythonw.exe C:\turnstile\turnstile_gateway.py`
("Run whether user is logged on or not").

**Linux (systemd)** — `/etc/systemd/system/turnstile.service`:
```
[Unit]
Description=EESBO turnstile gateway
After=network-online.target

[Service]
WorkingDirectory=/opt/turnstile
ExecStart=/usr/bin/python3 /opt/turnstile/turnstile_gateway.py
Restart=always

[Install]
WantedBy=multi-user.target
```
`sudo systemctl enable --now turnstile`

## Ishlash qoidalari

- Faqat `ValidateTicketAsync` → `success: true` bo'lsa ochiladi. Bilet shu zahoti "Ishlatilgan"
  bo'ladi, ikkinchi marta o'tib bo'lmaydi.
- Muzey bileti (`is_museum=true`) — har o'qishda bitta o'tish, limit tugaguncha.
- Internet yoki ЕЭСБО ishlamasa turniket **ochilmaydi** (xavfsiz rejim).
- Agentlar QR'ga qo'shgan qo'shimcha parametrlar (`&agent=...`) avtomatik olib tashlanadi.

# Testavimas be Arduino ir perėjimas prie įrangos

## Išbandykite dabar be įrangos

Trumpiausias paleidimas jau paruoštoje aplinkoje: **`.\start-demo.ps1`**. Jis pats paleidžia serverį, jei reikia, ir interaktyvų simuliatorių tame pačiame terminale. Žemiau pateiktas variantas su dviem terminalais, jei norite procesus valdyti atskirai.

1. Pirmame VS Code terminale paleiskite `.\start.ps1`. Jei serveris jau paleistas, antrą kartą jo nepaleiskite.
2. Atidarykite http://127.0.0.1:8001 ir prisijunkite. Duomenys: `backend/data/initial-credentials.txt`.
3. Kitame terminale paleiskite `.\start-simulator.ps1`.
4. Simuliatorius per tą pačią API, kurią naudos Arduino, siųs telemetriją. Su `--demo` jis administratoriaus vardu pridės **D3A01234** kortelę, jei tokios nėra. Tai tik demonstracinė kortelė, kurią vėliau galite pašalinti.
5. WEB viršuje turi būti **„Simuliatorius prisijungęs“**. Tai nėra fizinės įrangos būsena.

Simuliatoriaus komandas įrašykite jo terminale, po kiekvienos spauskite Enter:

| Komanda | Kas vyksta |
| --- | --- |
| `card` | Nuskaitoma numatyta demo kortelė D3A01234 |
| `card 99999999` | Nežinomos kortelės bandymas |
| `motion on` | PIR išėjimas tampa HIGH, judesys tęsiasi |
| `motion off` | PIR išėjimas tampa LOW |
| `status` | Vietinė režimo, PWM ir ryšio būsena |
| `disconnect` | Nutraukiamas simuliatoriaus ryšys su serveriu |
| `connect` | Ryšys atkuriamas |
| `quit` | Simuliatorius sustabdomas |

Nėra papildomų simuliatoriaus priklausomybių: naudojama Python standartinė biblioteka. Be automatinio demo kortelės kūrimo: `.\.venv\Scripts\python.exe tools\device_simulator.py`. Kitam serverio portui: `.\start-simulator.ps1 -Port 8003`.

## Patikros scenarijai

Kad testai būtų greitesni, WEB nustatymuose laikinai pasirinkite **pritemdyti po 10 s**, **išjungti po 20 s**, **pritemdytas ryškumas 25%**.

| Scenarijus | Veiksmai | Laukiamas rezultatas |
| --- | --- | --- |
| Registruota kortelė | Simuliatoriuje `card` | Prieiga suteikta, automatinis režimas, po telemetrijos ryškumas patvirtintas |
| Nežinoma kortelė | `card 99999999` | Prieiga atmesta, istorijoje įrašas, nauja sesija nesuteikiama |
| Pritemdymas ir išjungimas | `card`, palikti `motion off` | Po 10 s pritemsta, po 20 s išsijungia (leidžiama kelių s ryšio paklaida) |
| Judesys | `card`, tada `motion on` | Šviesa lieka įjungta; po `motion off` vėl skaičiuojamas laikmatis |
| Judesys be autorizacijos | Sulaukti išjungimo, tada `motion on` | Šviesa neįsijungia; reikia naujo `card` |
| WEB valdymas | WEB pasirinkti „Įjungta“, 65%, „Taikyti“ | Per kitą ryšio ciklą simuliatorius praneša 65% |
| Rankinis išjungimas | WEB „Išjungta“, „Taikyti“ | 0%; naujas `card` vėl pradeda automatinį režimą |
| Kortelės blokavimas | WEB užblokuoti D3A01234, tada `card` | Prieiga atmesta. Aktyvi ta kortele pradėta auto sesija nutraukiama |
| Teisės | Sukurti paprastą vartotoją, juo prisijungti | Valdymas prieinamas, kortelių / vartotojų / istorijos / nustatymų administravimas neprieinamas |
| Ryšio praradimas | `card`, `motion off`, `disconnect` | WEB po 15 s rodo atjungtą simuliatorių; vietinis PWM laikmatis vis tiek išjungia šviesą |
| Rankinio įjungimo ryšio apsauga | WEB „Įjungta“, palaukti patvirtinimo, `disconnect` | Po nustatyto išjungimo intervalo be serverio ryšio simuliatorius išjungia išėjimą |
| Duomenų išlikimas | `quit`, sustabdyti ir vėl paleisti serverį | Paskyros, kortelės, nustatymai ir istorija išlieka |

Baigę galite grąžinti 60 / 120 / 25 reikšmes. Simuliatorių sustabdykite `quit`. Demonstracinę kortelę pašalinkite per NFC kortelių puslapį. Istorija lieka audito žurnale; simuliatoriaus telemetrija pažymima „Simuliatorius“.

## Kai turėsite komponentus

**Pirmiausia sustabdykite simuliatorių.** Vienai patalpai numatytas vienas valdiklis; simuliatorius ir tikra plokštė vienu metu siųstų prieštaraujančią telemetriją.

1. Pagal README lentelę sujunkite UNO, PN532 (I2C), PIR, W5100, relę ir MOSFET. Patikrinkite maitinimo įtampas pagal konkrečių modulių dokumentaciją.
2. Paleiskite serverį. Suraskite savo LAN IPv4 per `ipconfig`. Parinkite laisvą Arduino adresą tame pačiame potinklyje.
3. Rankiniu būdu paruoškite `config.h` pagal README arba sugeneruokite jį (žemiau tik adresų pavyzdys):

   ```powershell
   .\tools\configure-arduino.ps1 -ServerIP 192.168.1.100 -DeviceIP 192.168.1.210 -Gateway 192.168.1.1
   ```

   Generatorius įrašo dabartinį privatų įrenginio raktą. Realūs adresai turi atitikti jūsų tinklą. Patikrinkite `RELAY_ACTIVE_LOW`.
4. Įdiekite README nurodytas bibliotekų versijas, pasirinkite UNO ir COM, įkelkite `LightingController.ino`.
5. Serial Monitor 115200 turi parodyti sistemos paleidimą, be pranešimo „PN532 nerastas“. PIR leiskite stabilizuotis. WEB turi parodyti **„Arduino prisijungęs“**.
6. Pridėkite tikrą kortelę. UID rodomas Serial Monitor, net kai kortelė dar neautorizuota. WEB kortelių sąraše priskirkite ją aktyviam vartotojui.
7. Pakartokite aukščiau pateiktus scenarijus su tikra kortele, judesiu ir LED. Vietoje `disconnect` atjunkite Ethernet kabelį. Vietoje simuliuoto PWM stebėkite tikrą LED ir relę.
8. Jei reikia patvirtinti tikrą elektros / šviesos išėjimą, pamatuokite jį: dabartinė telemetrija rodo programos nustatytą PWM, nepriklausomo šviesos jutiklio projekte nėra.

## Kas jau patikrinta programiškai

- API autorizacija, sesijos, rolės ir įrenginio raktas.
- Kortelių ir vartotojų registravimas / blokavimas.
- Automatinio režimo, laikmačių ir ryškumo logika.
- Simuliatoriaus vietinis veikimas nutrūkus ryšiui.
- Tikras HTTP ryšys tarp atskirai paleisto serverio ir simuliatoriaus procesų.
- WEB veikimas naršyklėje ir mobilusis išdėstymas.
- UNO eskizo kompiliacija su AVR ir nurodytomis bibliotekomis.

Kompiliacija ir simuliacija nepatvirtina laidų, komponentų elektrinio suderinamumo, konkretaus PN532 modulio nustatymų ar tikros tinklo instaliacijos. Šiuos punktus užbaigs pirmas bandymas su įranga.

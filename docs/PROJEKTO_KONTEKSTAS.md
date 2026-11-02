# Projekto kontekstas

Šaltiniai: pokalbio „Sistemos projekto tęsinys“ prieinama paskutinė dalis, pateikta prezentacija „Išmanioji apšvietimo valdymo sistema.pptx“ (projekto turinys 1–24 skaidrėse), esamas FastAPI kodas. Skaidrių šablono pavyzdžiai nuo 25 skaidrės nelaikomi sistemos reikalavimais.

## Paskirtis

Vienos patalpos išmanusis apšvietimas. Arduino UNO valdo fizinę grandinę, serveris autorizuoja NFC korteles, saugo duomenis ir perduoda WEB komandas. Telefonas naudoja adaptyvų WEB puslapį. Atskira Android ar iOS programėlė nekuriama.

## Realizuota veikimo sutartis

1. Sistema pradeda automatiniu režimu, šviesa išjungta.
2. PN532 nuskaito UID ir Arduino pateikia jį serveriui. Registruota, aktyvi kortelė, priskirta aktyviam vartotojui, įjungia šviesą ir automatinį režimą. NFC autorizacija pakeičia ankstesnį rankinį režimą.
3. PIR judesys pratęsia aktyvios autorizacijos laiką. Vien judesys, kai autorizacija pasibaigusi, šviesos neįjungia.
4. Nuo paskutinės autorizacijos arba judesio po 60 s šviesa pritemsta iki daugiausia 25%, po 120 s išsijungia. Tai pasirinktos pradinės vertės, nes skaidrėse konkretaus laiko nėra. Administratorius jas keičia.
5. Rankinis „Įjungta“ palaiko pasirinktą 1–100% ryškumą. Rankinis „Išjungta“ išjungia šviesą. Pasirinkus „Automatinis“ laukiama naujos NFC autorizacijos. Paspaudus „Taikyti“ išsaugoma komanda.
6. Ryškumą reguliuoja atskiras MOSFET per PWM. Relė tik įjungia ir atjungia LED maitinimą.
7. WEB atskiria pageidaujamą ryškumą nuo paskutinio įrenginio pranešto. Tai programinė išėjimo būsena, o ne nepriklausomas šviesos ar srovės matavimas.
8. Arduino kas 2 s siunčia telemetriją ir gauna komandą; WEB atnaujinamas kas 3 s. Po 15 s be telemetrijos įrenginys rodomas neprisijungęs. Tai periodinės HTTP užklausos, ne griežto realaus laiko ryšys.
9. Nutrūkus ryšiui naujos kortelės neautorizuojamos. Jau aktyvus automatinis režimas vietoje vykdo laikmatį ir PIR logiką. Rankinis įjungimas vietoje išjungiamas po `off_after_seconds` be sėkmingo ryšio. Atkūrus ryšį galioja serverio būsena; pasibaigusiai automatinei sesijai reikės NFC kortelės.
10. Kortelės blokavimas / pašalinimas ir jos savininko blokavimas nutraukia tai kortelei priskirtą automatinę sesiją. Komanda fizinę plokštę pasiekia per kitą sėkmingą ryšį.

## Prieigos

Vartotojas: prisijungti, stebėti būseną, pasirinkti režimą ir ryškumą, atsijungti.

Administratorius: visos vartotojo teisės, paskyrų kūrimas ir blokavimas, kortelių priskyrimas / blokavimas / šalinimas, įvykių istorija, laikmačių nustatymai. Administratorius negali užblokuoti savo paskyros.

Įrenginys: atskiras `X-Device-Key`, NFC autorizacija, komandų gavimas ir telemetrija. WEB sesija nesuteikia įrenginio teisių.

## Technologijų skirtumai

Skaidrėse minima ASP.NET Core + PostgreSQL. Ankstesniame pokalbyje jau pradėtas FastAPI ir planuota SQLite. Ši realizacija tęsia FastAPI + SQLite. Funkcinę viziją išsaugome, tačiau dokumentacijoje ir pristatyme technologijų sąrašą reikia suderinti. Skirtingose aparatūros iliustracijose matyti SPI ir I2C skaitytuvai; realizacija naudoja PN532 per I2C pagal skaidrių sąsajų aprašymą.

## Patikrinimo ribos

Automatiniai API testai ir naršyklės scenarijai tikrina programinę realizaciją. Arduino eskizas kompiliuojamas UNO plokštei. Į fizinę plokštę programa neįkelta ir tikra grandinė neišbandyta. Galutinai reikia patikrinti konkretaus PN532 modulio I2C režimą ir įtampą, relės aktyvų lygį, PIR išėjimą, MOSFET bei LAN adresus.

NFC UID yra mokomojo prototipo identifikatorius ir neapsaugo nuo kortelės klonavimo. W5100 įrenginio HTTP ryšys skirtas patikimam vietiniam tinklui. Viešai prieigai WEB srautui reikia HTTPS ir tinklo izoliacijos.

# ACC shared memory — довідка під логер

Витяг лише того, що потрібно логеру, плюс перелік корисного на майбутнє.
Джерела й розбіжності між ними — в кінці.

Мапінги ті самі, що в AC: `acpmf_physics`, `acpmf_graphics`, `acpmf_static`
(повне ім'я `Local\acpmf_*`; Python `mmap` з іменем без префікса потрапляє в той
самий namespace). Розміри, які використовує PyAccSharedMemory: physics 800,
graphics 1588, static 784 байти.

## Осторога: логер сам створює мапінги

`mmap.mmap(-1, size, tagname=...)` не тільки відкриває наявний мапінг, а й
**створює** його, якщо такого нема. Тобто логер, запущений до гри (а з автостартом
так і буде), створює `acpmf_*` своїм розміром — меншим, ніж потрібно грі.

Формально це мало б заблокувати грі публікацію телеметрії: `CreateFileMapping` з
уже існуючим іменем повертає наявний об'єкт, а `MapViewOfFile` з великим розміром
на малому об'єкті падає. На практиці працює — логер з автостартом ловить дані і в
AC, і в ACC. Найімовірніша причина: розмір section-об'єкта округлюється до
гранулярності сторінки (4096), а всі наші структури і сторінки обох ігор у ці 4096
вкладаються.

Поведінка не нова, вона була в логері з самого початку. Але якщо колись хтось
поскаржиться, що гра не віддає телеметрію саме коли логер стартував першим —
дивити треба сюди.

## Physics

Ідентичний AC до `abs` включно. Одна розбіжність у типі: `drs` в ACC-довідці
оголошений як `int`, в AC-довідці — `float`. Розмір 4 байти в обох випадках, тому
офсети не їдуть; при читанні в ACC-структурі оголошувати `c_int32`.

Порядок полів від `abs` до потрібного `brakeTemp` — усе це треба оголосити, навіть
те, що не читаємо, інакше офсет з'їде:

```
float abs
float kersCharge          # не використовується в ACC
float kersInput           # не використовується
int   autoShifterOn
float rideHeight[2]       # не використовується
float turboBoost
float ballast             # не використовується
float airDensity          # не використовується
float airTemp
float roadTemp
float localAngularVel[3]
float finalFF
float performanceMeter    # не використовується
int   engineBrake         # не використовується
int   ersRecoveryLevel    # не використовується
int   ersPowerLevel       # не використовується
int   ersHeatCharging     # не використовується
int   ersIsCharging       # не використовується
float kersCurrentKJ       # не використовується
int   drsAvailable        # не використовується
int   drsEnabled          # не використовується
float brakeTemp[4]        # <- потрібне
float clutch
```

Не заповнюються в ACC (тому не логуються): `wheelLoad[4]`, `tyreWear[4]`,
`tyreDirtyLevel[4]`, `camberRAD[4]`, `drs`, `cgHeight`, `numberOfTyresOut`.
Заповнюються і використовуються: `wheelSlip[4]`, `wheelsPressure[4]`,
`wheelAngularSpeed[4]`, `tyreCoreTemperature[4]`, `suspensionTravel[4]`, `tc`,
`abs`, `heading/pitch/roll`, `carDamage[5]`, `pitLimiterOn`.

Далі за `clutch` (нам поки не потрібне, але існує і заповнюється):
`tyreTempI/M/O[4]` не використовуються, `isAIControlled`,
`tyreContactPoint/Normal/Heading[4][3]`, `brakeBias`, `localVelocity[3]`,
`slipRatio[4]`, `slipAngle[4]`, `waterTemp`, `brakePressure[4]`,
`frontBrakeCompound`, `rearBrakeCompound`, `padLife[4]`, `discLife[4]`,
`ignitionOn`, `starterEngineOn`, `isEngineRunning`, `kerbVibration`,
`slipVibrations`, `gVibrations`, `absVibrations`.

`slipAngle[4]` — найцікавіше з невикористаного: прямий кут зносу, тобто те, що
`drift_report.py` зараз рахує з `heading` і `velocity`. Не беремо зараз лише тому,
що дрифт у нього в AC, а не в ACC.

## Graphics

Ідентичний AC до `normalizedCarPosition`. Далі:

```
int   activeCars
float carCoordinates[60][3]
int   carID[60]
int   playerCarID
float penaltyTime
int   flag                # enum ACC_FLAG_TYPE
int   penalty             # enum ACC_PENALTY_TYPE
int   idealLineOn         # <- потрібне
int   isInPitLane         # <- потрібне
float surfaceGrip         # див. розбіжність нижче
int   mandatoryPitDone
float windSpeed
float windDirection
int   isSetupMenuVisible
int   mainDisplayIndex
int   secondaryDisplayIndex
int   TC
int   TCCUT
int   EngineMap
int   ABS
float fuelXLap            # середня витрата палива на коло, л  <- потрібне
int   rainLights
int   flashingLights
int   lightsStage
float exhaustTemperature
int   wiperLV
int   driverStintTotalTimeLeft   # мс
int   driverStintTimeLeft        # мс
int   rainTyres
int   sessionIndex
float usedFuel            # спалено з останньої заправки
wchar deltaLapTime[15]
int   iDeltaLapTime
wchar estimatedLapTime[15]
int   iEstimatedLapTime
int   isDeltaPositive
int   iSplit
int   isValidLap          # чи коло валідне для таймінгу  <- потрібне
float fuelEstimatedLaps   # скільки кіл лишилось на цьому паливі  <- потрібне
wchar trackStatus[33]
int   missingMandatoryPits
float Clock
...
```

Ключове для нашої задачі: **ACC сам віддає витрату палива** (`fuelXLap`),
**залишок кіл** (`fuelEstimatedLaps`) і **валідність кола** (`isValidLap`). AC
нічого з цього не має. Тому власна модель палива все одно потрібна (щоб число в
AC і в ACC вважалося однаково), але в ACC її можна звірити з грою — див. критерії
в спеці.

Ще: `tyreCompound` в ACC повертає `dry_compound` / `wet_compound`, а
`mfdTyrePressureLF/RF/LR/RR` і `mfdFuelToAdd` віддають значення з MFD — саме те,
що знадобиться для «рекомендованих тисків» у майбутньому скілі.

## Static

Префікс ідентичний AC до `sectorCount`. Логер читає лише `carModel` і `track`,
тому клас спільний для обох ігор. Далі в ACC ідуть `maxTorque`, `maxPower`,
`maxRpm`, `maxFuel`, `suspensionMaxTravel[4]`, `tyreRadius[4]`, `maxTurboBoost`,
… — не потрібні.

## Перевірено на живій сесії (05.08.2026, ACC practice)

- **Офсети правильні.** `brakeTemp` дав 27 °C у стоянні (ambient) і до 654 °C
  спереду / 398 °C позаду під торможіння, тобто перед гарячіший за зад — фізично
  вірна картина для GT3. При зсунутому офсеті там було б сміття або нулі.
- **`isValidLap` скидається на перетині лінії.** У логах out-lap тримав 0 з t=9.06
  і перекинувся на 1 рівно в момент перетину (t=95.17). Тобто читати прапорець у
  момент перетину не можна — валідність кола треба латчити протягом кола. Заодно:
  в ACC out-lap з боксів завжди невалідний.
- **`isInPitLane` неможливо залогувати** при нашій логіці: файл фіналізується на
  в'їзді в піт-лейн, тому рядок з одиницею не пишеться ніколи. Колонку прибрано;
  спостережуваний ефект пітового заїзду — що CSV закрився.
- **`fuelXLap` збігається з власною моделлю**: 2.508 від гри проти 2.51
  розрахованих по різниці палива між перетинами (Red Bull Ring, M4 GT3).
- `idealLineOn` = 1, `tyreCompound` — як і описано в доці.

`surfaceGrip` на живій сесії ще не дивили (у CSV його немає навмисно) — для цього
є `probe_sim.py`.

## Розбіжність між джерелами

`surfaceGrip`: офіційна дока Kunos описує його як «Ideal line friction
coefficient», а PyAccSharedMemory коментує його як «Return always 0».
Не покладаємось ні на що: перевіряємо на живій сесії, і колонку додаємо тільки
якщо значення реально не нульове.

## Інші джерела логів ACC (не shared memory)

Знайдено на диску, в обсяг логера не входить, але записано щоб не шукати вдруге:

- `Documents/Assetto Corsa Competizione/MoTeC/*.ld` + `.ldx` — ACC вміє писати
  телеметрію в MoTeC-форматі нативно, з вищою частотою, ніж shared memory.
  **Відхилено власником проєкту**: працювати з MoTeC на практиці задорого. Не
  пропонувати повторно.
- `Documents/Assetto Corsa Competizione/Results/*.json` — **UTF-16-LE**, покілові
  записи по всіх машинах:
  `{"carId":0,"driverId":0,"lapTime":102147,"splits":[36407,33657,32082],"fuel":62.0,"flags":0,"timestampMS":151952.5}`.

  Обережно з полем `fuel`: воно **не** залишок палива на колі, а стартове
  завантаження машини — константне на всю сесію (перевірено на всіх чотирьох
  файлах: у гравця 62.0 на 24 колах, у AI 79.382 і 77.795 без змін). Різниця
  значень між машинами виглядає як витрата, але нею не є. Для тестів моделі
  палива це джерело не годиться.

  Що звідти справді придатне: `lapTime`, `splits`, `timestampMS` і бітове поле
  `flags` (спостережені значення 0, 1, 4, 5, 8, 1024, 1025 — схоже на валідність
  та причини її втрати; точна розшифровка не з'ясовувалась, бо не була потрібна).
- `sdk/` в інсталяції ACC містить тільки `server_sdk_readme.txt`; після 1.5.7
  Kunos переніс серверний і Broadcast SDK в окремий Steam Tools item. Shared
  memory доки в інсталяції немає взагалі.

## Джерела

- Офіційна дока Kunos, `ACCSharedMemoryDocumentationV1.8.12.pdf` — PDF-вкладення
  в темі [ACC Shared Memory Documentation](https://www.assettocorsa.net/forum/index.php?threads/acc-shared-memory-documentation.59965/);
  копія лежить у репозиторії [rrennoir/PyAccSharedMemory](https://github.com/rrennoir/PyAccSharedMemory).
- [rrennoir/PyAccSharedMemory](https://github.com/rrennoir/PyAccSharedMemory),
  `src/pyaccsharedmemory.py` — послідовний розпак, тобто порядок полів у коді
  дорівнює порядку в структурі. Використано як незалежну звірку з PDF.

# Health data: how it is read, and what is not covered yet

The [Health tab](apps/health.md) shows what it can show *reliably*. This page
explains how each part is read, what each part rests on, and what is left out
and why. Where something is a known gap, this page says what would be needed
to close it, so that it can be worked on.

## The database

Health lives in `HealthDomain/Health/healthdb_secure.sqlite` (the data),
`healthdb.sqlite` (the sources: which app or device wrote what) and
`HealthDomain/MedicalID/MedicalIDData.archive` (the Medical ID card). It is
only present in **encrypted** backups. The main database can be very large (the
one this was written against held 1.5 million samples in 378 MB); the tab
copies it to a temporary working folder when it is first opened and deletes it
when the backup is closed.

The core of it is three tables:

- `samples`: one row for every measurement or event: when it started and ended
  and a number, `data_type`, for what *kind* of sample it is.
- `quantity_samples`: for the samples that are measurements, the value.
- `category_samples`: for the samples that are events or states (sleep stages,
  stand hours), the value.

Heart rate, steps, sleep and the hundred-odd other kinds are all rows of
`samples` told apart only by that **number**.

## The problem: Apple does not publish the numbers

The public HealthKit interface names its kinds with strings
(`HKQuantityTypeIdentifierStepCount`); the numbers the database uses
internally are not documented, and they are not stable knowledge to copy from
another tool's list. Guessing wrongly would show a heart rate as a distance.
So this program does not guess.

### Naming the kinds from the database itself

The database has a table of *shared summaries* whose names contain the kind
they summarise, for example
`Summaries_[HKQuantityTypeIdentifierStepCount]_CurrentValue_...`, and a table
listing the numbers each summary covers. Joining the two gives a name for a
number *from the file itself*. A number is named **only when exactly one name
is tied to it**; a number with none, or with two different names, is shown as
**Type N**.

This was checked against independent data in a real backup: the numbers named
*active energy burned*, *exercise time*, *step count*, *flights climbed* and
the stand hours produced day totals that match the phone's own activity
summaries (correlation 1.000 for active energy and exercise minutes, and the
stand hours matched on every day compared), and the workout statistics used
the numbers named heart rate, distance and energies.

### Units

A kind's `quantity` is stored in an internal unit that is different for each
kind: heart rate in beats per *second*, resting heart rate in beats per
*minute*, body fat and blood oxygen as *fractions* (0.25, not 25 %), height in
metres, weight in kilograms. Where the sample also records the unit it was
entered in (`original_unit`, `original_quantity`), the stored value was compared
with it. The **Body and vitals** table is limited to the kinds for which this
was done:

| Shown as | Stored as | Shown in |
|---|---|---|
| Weight, Lean body mass | kilograms | kg |
| BMI | kg/m² | kg/m² |
| Body fat | a fraction | % |
| Height | metres | cm |
| Resting heart rate, Walking heart rate | beats per minute | bpm |
| Blood oxygen | a fraction | % |
| VO2 max | mL/(kg·min) | mL/(kg·min) |
| Heart rate variability (SDNN) | milliseconds | ms |
| Respiratory rate | breaths per second | breaths/min |

### The other parts

- **Daily activity** comes from the phone's *activity caches*, its own daily
  summaries. They count each step and calorie once, where adding up the raw
  samples counts them twice when an iPhone and a watch both recorded them (the
  raw step samples of one backup summed to about double the summary).
- **Workouts** use the activity types of HealthKit's *public* list (Running,
  Walking, Cycling...), whose numbers are documented, with the phone's own
  statistics for energy (kcal), distance (m) and heart rate (stored per second,
  shown per minute). A workout's route is its location series; routes, found
  through the associations table, are written to GPX.
- **Sleep** uses HealthKit's public sleep stages: 0 in bed, 1 asleep
  (unspecified), 2 awake, 3 core, 4 deep, 5 REM. Their durations in a real
  backup fit (awake spells are minutes, in-bed spans are hours).
- **Medical ID** is an archived property list; the program reads the labelled
  fields of the card.

## What is not covered yet

### Kinds the database does not name

In the backup this was written against, 63 of the 92 kinds present were named
and 29 were not (most with few samples, a few with thousands). They are counted
in **Data types** as "Type N". Naming one needs an independent check *per kind*:
a way to tell what it is from data, the way active energy was matched against
the activity summaries. If you recognise a kind, an issue with the number, what
it looks like in the database (counts, value ranges, units) and what you
believe it is would help. **Do not post your data.**

### Values of most kinds

Only the kinds in the table above are interpreted. The rest (hundreds of
thousands of raw heart rate samples, steps, distance, audio exposure, the
walking-steadiness measures, nutrition...) are counted but not listed, because
each stores its numbers in its own internal unit and each would need to be
checked against values recorded in a known unit before being shown. Showing a
wrong unit would be worse than showing nothing.

### Sleep per night

Sleep is listed by stage (the **Sleep** table), and added up per night in
**Sleep per night**. Adding it up needs to know which *day* a night belongs to
**where the phone was**, and the database records only the *name* of the time
zone of each sample (`data_provenances.tz_name`). Turning a name into an offset
needs a time zone database, which Python provides only when the operating
system has one. macOS and Linux have one; **Windows does not**, so for this
table Windows needs the optional `tzdata` package:

```
pip install tzdata
```

(it is in `requirements-optional.txt`, and nothing else needs it). Without a
time zone database the stages are still listed and the table says why it is
missing, rather than guessing an offset.

The rules, which the tests check:

- A **night** is a run of sleep records in which no record starts more than
  **four hours** after the latest end of the ones before it. A nap is a short
  night.
- A night belongs to the **day you woke up**: the local date of its last
  period of sleep, in the time zone that record was made in (so a night in
  another country is placed by the clock there, and a change of daylight
  saving time is handled by the time zone database).
- Records of two devices that overlap (a phone's "in bed", a watch's stages)
  are counted **once**: each total is the *union* of its records, never their
  sum. "Asleep" is the union of the asleep stages (unspecified, core, deep,
  REM).
- A night whose records name no time zone, or one the computer does not know,
  is left out and the table's note says so.

Run on the sleep records of a real backup, the nights came out as plausible
nights (hours in bed, asleep, stages inside the time asleep) and the totals of
each night agreed with its own stage records.

### Other data in the database

These are read now. How each rests on the data, and how far it was checked:

- **Medications** and their log. The medications you track in the Health app
  (name, form, ingredients, the product), and the log of doses: for each due
  dose, the medication, when it was due, the amount and its status. The names
  are in the medication's localized strings; which string holds the name, the
  ingredients, the form and the full product name was settled by looking at
  what a real backup holds, and **the owner of that backup confirmed the four
  columns** against what the Health app shows. The status of a dose is shown
  in words only for the two values the data explains: **1 = the dose never got
  an answer**, **4 = it was taken** (every dose with 4 has an amount logged);
  these two come from the data and have not been confirmed by the owner. Any
  other value is shown as "Status N" rather than guessed (iOS 26 has one dose
  with status 5). iOS 26 also records the unit of a dose ("tablet"), shown
  after the amount.
- **Contents of health records.** Labs, immunizations, conditions, allergies
  and procedures, prescriptions and clinical documents are stored as FHIR (a
  standard format for health records) inside the database; they are read as
  the provider sent them: the test, the result with its unit and reference
  range, the date, the provider.
- **Files of clinical documents.** For some documents the phone also
  downloaded the file itself (a PDF report, a note as HTML or RTF). Health
  keeps each in `HealthDomain/Health/Files/<identifier>` in Apple's encrypted
  archive format (the file starts with `AEA1`), **with the key in the Health
  database itself** (`attachments.encryption_key`, an archived object holding a
  32-byte `sym_key`), and `medical_downloadable_attachments` says which clinical
  record each file belongs to. With the key the file opens; every part of it is
  checked (a keyed check value for each part, and a SHA-256 for each segment),
  so a wrong key or a damaged file is refused and never gives wrong bytes. The
  documents table shows how many files a document has, and **Export...**,
  *The documents' files* saves them opened, with the right extension. The
  format is described, not documented by Apple; the reader was written from
  what others published and checked byte for byte against another
  implementation (kinnay/AEA) on the 13 files of a real backup, and a test
  holds an archive made by that implementation. Only the profile Health uses
  (a symmetric key) is supported; files compressed with LZFSE or LZ4 need the
  optional `pyliblzfse` or `lz4` package (the Health files are not
  compressed).
- **Awards** (Fitness): the database holds the *internal* name of each award
  and when it was earned. The names the Fitness app shows are not in the
  backup, so the internal name is made readable and shown with the original.
- **Sleep schedules**: the schedules you set, with their times, as the clock
  times of the schedule, and the changes made for a single day.
- **Audiograms** (hearing tests): each frequency tested with the level of the
  left and right ear. The values and their units (Hz, dB HL) are written in
  the archive that stores them, so nothing is assumed.
- **Events, symptoms and cycle tracking**: stand hours, hand washing, loud
  audio events and mindful sessions, the symptoms you logged (with their
  severity) and cycle tracking (flow, ovulation tests, pregnancy tests, cervical
  mucus, contraceptives, sexual activity). Values are shown with the words that
  HealthKit's public documentation gives for them; a value outside that list is
  shown as "Value N".
- **Data of other people shared with you** (Activity sharing): the activity
  summaries and workouts that friends sent to this phone. The database holds
  **no names** for them, so the friends are numbered (Friend 1, Friend 2...).

### Still not covered

- **ECG waveforms.** No backup used so far held one, so how they are stored
  could not be checked. They are not read.
- **Documents whose file was never downloaded.** For most clinical documents
  in the backups used, the phone has only the record, not the clinic's file
  (the database says so: the download was never made). Nothing can be shown
  for those.
- **Fitness Intelligence (iOS 26).** iOS 26 keeps derived summaries of the
  rings, workouts and Fitness+ (streaks, best workouts, counts) in tables
  named `FitnessIntelligencePlugin_...`, as binary records whose layout is not
  known. They are not read; the daily activity, workouts and awards they
  summarise are.
- **Immunizations, cycle tracking and the workouts of friends** were written
  from the database's layout and public documentation; the backups used had no
  such rows, so these tables were tested on generated data only.
- **Dose statuses other than 1 and 4**, and where a dose was logged *from*
  (origin), are shown as numbers until a backup shows what they mean.

Everything above was checked on real backups of **iOS 16.7 and iOS 26.6** (see
[iOS versions](IOS_VERSIONS.md)); the two came out alike, which is expected
because their Health data is the same account. What iOS 26 changed in the
database, and how it is handled: the table that links a workout to its route
names its columns by direction (the route links were found only on iOS 16
before), medication doses carry their unit ("tablet"), and a new dose status
appears.

### Raw files

Everything in the database is always available through **Extract original
files...**, which copies the databases exactly as the backup holds them, so you
can query anything not covered here with any SQLite tool.

## Where the checks live

The tests in `tests/test_health.py` build a small Health database with the same
tables and check each rule above (naming only a single-name number, the
conversions, the routes, the sleep stages, the Medical ID). The newer parts have
a file each: `tests/test_health_sleep.py` (nights, time zones, daylight saving
time, overlaps), `test_health_records.py` (the FHIR records),
`test_health_medications.py`, `test_health_events.py` and
`test_health_more.py` (awards, schedules, audiograms, friends). See
[Testing](TESTING.md).

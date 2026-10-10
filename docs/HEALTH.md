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

Sleep is listed by stage. Adding it up per night needs to know which *day* a
night belongs to **where the phone was**, and the database records only the
*name* of the time zone of each sample. Turning a name into an offset needs a
time zone database, which Python provides only when the operating system has
one (Windows does not; the `tzdata` package would fill the gap, and is a
candidate dependency).

### Other data in the database

Not read yet: medications and their doses, ECG and audiogram waveforms, cycle
tracking and symptoms, the *contents* of health records (labs, immunizations;
only their names are listed), clinical documents, Fitness+ and awards, and the
data of other people shared with you.

### Raw files

Everything in the database is always available through **Extract original
files...**, which copies the databases exactly as the backup holds them, so you
can query anything not covered here with any SQLite tool.

## Where the checks live

The tests in `tests/test_health.py` build a small Health database with the same
tables and check each rule above (naming only a single-name number, the
conversions, the routes, the sleep stages, the Medical ID). See [Testing](TESTING.md).

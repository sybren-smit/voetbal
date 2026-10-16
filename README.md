# Voetbal-agenda: WVV'34 2 in je iPhone-agenda

Dit project haalt elke 3 uur het programma van **WVV'34 2** op van de clubsite
(dezelfde Sportlink-gegevens als in voetbal.nl) en zet het in een agenda-link.
Je iPhone abonneert zich één keer op die link en houdt hem daarna zelf bij:
nieuwe wedstrijden, gewijzigde aanvangstijden, afgelastingen en uitslagen.

Bronnen: <https://www.wvv34.nl/wvv34-2-ve-zondag-speeldag-man> en
<https://www.wvv34.nl/programma> (het script leest beide; als er één
verandert of uitvalt, werkt de andere nog).

Wat je in je agenda krijgt:

- **Titel:** `RKHVV 3 - WVV'34 2`, na afloop met uitslag `(3-1)`
- **Locatie:** het sportpark (thuiswedstrijden met "Hengevelde" erbij)
- **Herinnering:** 1 uur voor de aftrap
- **Afgelast:** titel begint met `AFGELAST:` en de afspraak wordt geannuleerd
- **Verplaatst:** de oude afspraak verdwijnt en de nieuwe verschijnt
- **Link** naar de wedstrijddetails op wvv34.nl

---

## Eenmalig instellen (± 10 minuten, gratis)

### 1. Zet de bestanden op GitHub

1. Maak een gratis account op <https://github.com> (als je dat nog niet hebt).
2. Klik rechtsboven op **+** → **New repository**.
   Naam bijvoorbeeld `voetbal-agenda`, kies **Public**, klik **Create repository**.
3. Klik op **uploading an existing file** en sleep alle bestanden uit deze map
   erin, *inclusief* de map `.github` (op een Mac zie je die met
   `Cmd + Shift + .`). Klik **Commit changes**.

   > Lukt het slepen van `.github` niet? Klik dan in je repository op
   > **Add file → Create new file**, typ als naam
   > `.github/workflows/sync.yml` en plak de inhoud van dat bestand erin.

### 2. Laat hem de eerste keer draaien

1. Ga naar het tabblad **Actions**. Klik op de groene knop om workflows aan te zetten
   als GitHub daarom vraagt.
2. Klik links op **Voetbal-agenda bijwerken** → **Run workflow** → **Run workflow**.
3. Na ± 30 seconden staat er een groen vinkje. Er is nu een map `docs/` met
   `wedstrijden.ics`.

### 3. Zet de agenda-link online

1. Ga naar **Settings** → **Pages**.
2. Bij *Source* kies **Deploy from a branch**, branch **main**, map **/docs**,
   klik **Save**.
3. Na een minuut staat bovenaan je link, bijvoorbeeld
   `https://JOUWNAAM.github.io/voetbal-agenda/`.
   Je agenda-link is die link met `wedstrijden.ics` erachter:

   `https://JOUWNAAM.github.io/voetbal-agenda/wedstrijden.ics`

### 4. Abonneren op je iPhone

1. Open **Instellingen** → **Agenda** → **Accounts** → **Voeg account toe**
   → **Andere** → **Voeg agenda-abonnement toe**.
2. Plak je link uit stap 3 en tik **Volgende** → **Bewaar**.
3. Kies bij *Account* voor **iCloud** als je hem ook op je iPad/Mac wilt.

Klaar. Je ziet nu een agenda **Voetbal WVV'34 2** in de Agenda-app.

> **Tip:** iOS haalt abonnementen standaard niet heel vaak op. Onder
> **Instellingen → Agenda → Accounts → Nieuwe gegevens ophalen** kun je dit
> vaker laten gebeuren.

---

## Aanpassen (optioneel)

Ga naar **Settings → Secrets and variables → Actions → tabblad Variables →
New repository variable**:

| Naam | Wat het doet | Voorbeeld |
|---|---|---|
| `TEAM_NAAM` | ander team volgen | `WVV'34 1` |
| `TEAM_URLS` | andere pagina('s), komma-gescheiden | `https://www.wvv34.nl/programma` |
| `AGENDA_NAAM` | naam van de agenda | `Mijn wedstrijden` |
| `WEDSTRIJDDUUR_MIN` | lengte van de afspraak in minuten | `120` |
| `PLAATS_THUIS` | plaats bij thuiswedstrijden | `Hengevelde` |

Wil je ooit verzameltijden, kleedkamers en scheidsrechter erbij? Vraag de
websitebeheerder van WVV'34 om de **Sportlink Club.Dataservice client ID**
en zet die onder **Secrets** als `SPORTLINK_CLIENT_ID` (met de variabele
`TEAMS` = `WVV'34 2`). Het script schakelt dan vanzelf over op die bron.

## Als het een keer niet werkt

- In **Actions** staat een rood kruis: klik erop voor de melding. Meestal is
  de opbouw van de clubsite veranderd.
- Lokaal testen: sla de programmapagina op als `pagina.html` en draai
  `python3 sync.py --test pagina.html`. Je ziet dan precies welke wedstrijden
  hij herkent.

Let op: de agenda-link is openbaar voor wie hem kent. Er staan alleen
openbare wedstrijdgegevens in, dezelfde die ook op wvv34.nl staan.

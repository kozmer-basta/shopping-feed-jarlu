# Mini Mergado – Google Shopping feed → OpenAI (ChatGPT Ads)

Každých 6 hodín si stiahne Google Shopping XML feed, prevedie ho do formátu OpenAI
a zverejní ho ako CSV na stálej adrese:

```
https://<vaše-github-meno>.github.io/<názov-repozitára>/openai_feed.csv
```

Túto adresu zadáte do OpenAI Ads Managera ako **Hosted URL**. Všetko beží zadarmo na GitHube.

---

## Nasadenie (cca 15 minút, jednorazovo)

1. **Účet.** Zaregistrujte sa na <https://github.com> (zadarmo, bez karty).
2. **Repozitár.** Vpravo hore kliknite na **+ → New repository**.
   - Názov napr. `topanocky-openai-feed`
   - Zvoľte **Public** (GitHub Pages a Actions sú pre verejné repozitáre zadarmo)
   - Kliknite na **Create repository**
3. **Nahranie súborov.** Na stránke repozitára kliknite na **uploading an existing file**
   a pretiahnite tam `convert.py`, `config.json`, `README.md` a priečinok `docs`.
   Kliknite na **Commit changes**.
   Potom pridajte workflow: **Add file → Create new file**, do názvu napíšte presne
   `.github/workflows/feed.yml`, vložte obsah súboru `feed.yml` z balíka a kliknite na **Commit changes**.
   > Priečinok `.github` je na Macu skrytý, preto je spoľahlivejšie súbor vytvoriť takto ručne.
4. **Práva pre robota.** Otvorte **Settings → Actions → General**. Dole v časti
   *Workflow permissions* zvoľte **Read and write permissions** a kliknite na **Save**.
5. **Zapnutie stránky.** Otvorte **Settings → Pages**. V časti *Source* zvoľte
   **Deploy from a branch**, branch **main** a priečinok **/docs**, potom **Save**.
6. **Prvé spustenie.** Na záložke **Actions** otvorte workflow **OpenAI feed**,
   kliknite na **Run workflow** a počkajte na zelenú fajku (asi 1 minúta).
7. **Kontrola.** Otvorte `https://<meno>.github.io/<repozitár>/openai_feed.csv`.
   Prehliadač by mal zobraziť alebo stiahnuť CSV súbor.
8. **OpenAI Ads Manager.** Vo **Feeds** vytvorte nový feed s možnosťou **Hosted URL**
   a vložte doň adresu z kroku 7.

Hotovo. Feed sa odteraz obnovuje automaticky.

---

## Nastavenia (`config.json`)

Upravíte ich priamo na GitHube: otvorte súbor, kliknite na ikonu ceruzky a dajte **Commit**.
Po uložení sa feed hneď pregeneruje.

| Nastavenie | Čo robí |
|---|---|
| `feed_url` | Adresa zdrojového Google feedu |
| `seller_name` | Názov obchodu (povinné pole OpenAI) |
| `seller_url`, `return_policy_url` | Adresa obchodu a stránky s podmienkami vrátenia tovaru |
| `default_brand` | Použije sa, keď produkt nemá značku. Ak zostane prázdne, produkt bez značky sa vynechá. |
| `exclude_out_of_stock` | `true` = do reklám nepôjdu vypredané produkty |
| `exclude` | Vylučovacie pravidlá, napr. `[{"field": "title", "contains": "darčeková poukážka"}]` |
| `ads_eligible` | `false` = všetky produkty vypnete z reklám |
| `custom_labels_to_ads_metadata` | `true` = `custom_label_0–4` sa prenesú do `ads_metadata` |
| `max_drop_ratio` | Poistka: ak počet produktov klesne o viac ako 50 %, starý feed sa ponechá |

## Kontrola chýb

Po každom behu sa vedľa feedu vytvorí `report.json`:
`https://<meno>.github.io/<repozitár>/report.json`

Report obsahuje počty produktov a zoznam problémov:
- **error** – produkt nemá povinné pole (obrázok, cenu, značku…), preto bol vynechaný
- **warning** – produkt sa exportoval, ale niečo sa doplnilo alebo vynechalo (napr. neplatný GTIN)

## Poistky

- Ak sa zdrojový feed nepodarí stiahnuť alebo je poškodený, beh skončí chybou
  a v OpenAI zostane posledný dobrý feed. GitHub vám o tom pošle e-mail.
- Ak sa katalóg naozaj zmenší o viac ako polovicu (napr. sezónna zmena),
  dočasne zvýšte `max_drop_ratio` na `0.9`, spustite workflow a hodnotu vráťte späť.

## Mapovanie polí

| Google | OpenAI |
|---|---|
| `g:id` | `item_id` |
| `title` | `title` (max. 150 znakov) |
| `description` (bez HTML) | `description` |
| `link` | `url` |
| `g:brand` | `brand` |
| `g:image_link` / `g:additional_image_link` | `image_url` / `additional_image_urls` |
| `g:availability` (`in stock`…) | `availability` (`in_stock`…) |
| `g:price` / `g:sale_price` (`39,90 EUR`) | `price` / `sale_price` (`39.90 EUR`) |
| `g:item_group_id` + `g:color` / `g:size` | `group_id`, `listing_has_variations`, `variant_dict` |
| `g:gtin` (so skontrolovanou kontrolnou číslicou), `g:mpn` | `gtin`, `mpn` |
| `g:product_type` | `product_category` |
| `g:shipping/g:price` | `shipping_price` |
| `g:gender`, `g:age_group`, `g:condition`, `g:material` | rovnako pomenované polia |

# Urban development–climate evidence extraction

Python 3.10+; standard library only. Fill `data/input_sample.csv` with one
article per row and unique DOI values. The supplied header-only file is a
blank input template.

Set `DEEPSEEK_API_KEY`, `QWEN_API_KEY`, `ZHIPU_API_KEY` and
`QWEN_BASE_URL` in your environment before processing records. Model names
and request settings are in `api_common.py`.

Run the files in this order from this directory:

1. `python 01_screen.py` — screen titles and abstracts with three independent
   calls per article. Outputs `output/screening.csv` and
   `output/screened_included.csv`.
2. `python 02_round1.py --provider DSflash --run 1` — identify location,
   development purpose and its primary action. Repeat with run 1, 2 and 3
   for each of `DSflash`, `Qwenflash` and `Zhipu` (nine commands).
   Outputs are separate files in `output/round1/`.
3. `python 03_round2.py --provider DSflash --run 1` — use the corresponding
   Round 1 record and original title/abstract to classify development topic,
   action, climate outcome, relation nature and research type. Repeat the same
   nine provider/run combinations after Round 1 is complete. Outputs are
   separate files in `output/round2/`.
4. `python 04_consensus.py` — within each model, take the mode of its three
   runs for each field; two agreeing model modes determine the result. If all
   three differ, use all available saved votes. Ties and action-category
   mismatches remain marked for review. Output: `output/consensus_3x3.csv`.

The screening, Round 1 and Round 2 prompts are included in their respective
step files. Each extraction request is a separate API call. The
successful model JSON is retained in each provider/run CSV. Re-running a
provider/run command resumes from saved successful rows.

`data/urban_climate_evidence_dataset.xlsx` is the accompanying full research
dataset. `data/city_attributes.xlsx` contains one row per matched city ID
with the city attributes used in the analyses. Running this sample workflow
creates new outputs in `output/`; it does not overwrite either supplied data
file.

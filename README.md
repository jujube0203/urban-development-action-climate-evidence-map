# Urban development–climate evidence extraction

Code and prompts for screening urban-study titles and abstracts and extracting development topic–urban action–climate impact links. 
The full evidence base is available at `data/urban_development_climate_evidence_database_v1.xlsx`.

Use Python 3.10+. Add records to `data/input_sample.csv` .

Set `DEEPSEEK_API_KEY`, `QWEN_API_KEY`, `ZHIPU_API_KEY` and `QWEN_BASE_URL` as environment variables. Model IDs and request settings are in `api_common.py`.

Run these steps in order from this folder:

1. `python 01_screen.py` — screen studies for inclusion.
2. `python 02_round1.py --provider DSflash --run 1` — extract city, country, development-purpose phrase and action phrase. 
3. `python 02b_round1_consensus.py` — vote on the four Round 1 fields and save `output/round1_consensus.csv`.
4. `python 03_round2.py --provider DSflash --run 1` — classify the linked topic, action, climate outcome, relation and study type using the title, abstract and Round 1 consensus. 
5. `python 04_consensus_linkage_vote.py` — vote on complete topic–action–outcome category links and save `output/consensus_linkage_9vote.csv`.

Intermediate CSVs and raw model responses are saved in `output/`; rerunning a provider/run command resumes completed records. `data/city_attributes.xlsx` supplies city attributes for subsequent analyses.

## License and data

Code and documentation are MIT-licensed (`LICENSE`). See `data/README.md` for data reuse and attribution considerations.

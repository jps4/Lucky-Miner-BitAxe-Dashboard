# Lucky-Miner-BitAxe-Dashboard

Implements a Miner Dashboard (BitAxe / Lucky Miner) to show all current and historical data. Works for both mobile and desktop

<img width="1914" height="917" alt="image" src="https://github.com/user-attachments/assets/5696f25a-e0d9-4380-a2e9-7e0cf75530df" />

<img width="380" height="655" alt="image" src="https://github.com/user-attachments/assets/d9c47062-2939-44be-859d-7a5fcb936386" />
<img width="302" height="525" alt="image" src="https://github.com/user-attachments/assets/e78c6a18-cfb6-414c-9303-c9b193cd3b3a" />



Data from Miner is retrieved via WebSockets and REST call. Python backend provides two endpoints, <b>/data<b> to obtain real time statistics from
Miner, and <b>/history</b>, which exports a list of obtained difficulties (greater than 10K) and timestamp.

Frontend renders a complete dashboard on desktop devices, including:
- Main KPIs:
    - total occurencies
    - best diff
    - time since last >=1M diff hash
    - number of diffs >=1G
    - total hashrate (extracted from 10K diff hashes)
    - luck (weighted calc from Top 10 hits in current range)
    - new hashes from dashboard load
- Current session: parameters provided by Miner (temp, power, hashrate, pool diff...) by WebSockets. Support for 2 miners (virtually N with minimal effort)
- Latest best difficulties
- Graphs with occurrences and distribution of difficulties (logaritmic y-axis to show Poisson-distribution shape)

All information could be set to several time ranges (today, last 7 days, month...)

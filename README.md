# Lucky-Miner-BitAxe-Dashboard

Implements a Miner Dashboard (BitAxe / Lucky Miner) to show all current and historical data. Works for both mobile and desktop

<img width="1906" height="929" alt="image" src="https://github.com/user-attachments/assets/dcf15e14-3fe0-41e3-bb61-dad34439244b" />

Data from Miner is retrieved via WebSockets and REST call. Python backend provides two endpoints, <b>/data<b> to obtain real time statistics from
Miner, and <b>/history</b>, which exports a list of obtained difficulties (greater than 10K) and timestamp.

Frontend renders a complete dashboard on desktop devices, including:
- Main KPIs: total occurencies, best diff, time since last >=1M diff hash, number of diffs >=1G, total hashrate (extracted from 10K diff hashes), and new hashes from dashboard load
- Current session: parameters provided by Miner (temp, power, hashrate, pool diff...)
- Latest best difficulties
- Graphs with occurrences and distribution of difficulties (logaritmic y-axis to show Poisson-distribution shape)

All information could be set to several time ranges (today, last 7 days, month...)

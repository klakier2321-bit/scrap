# AI Agents

Ten katalog istnieje jako fundament pod przyszłą warstwę agentów AI.
Będzie zawierał role, taski, workflowy, prompty i zasady pracy agentów.

Na tym etapie to tylko struktura organizacyjna pod przyszłe środowisko CrewAI, bez uruchamiania agentów i bez kodu wykonawczego.

Najważniejszym agentem koordynującym jest `system_lead_agent`, który prowadzi rozwój projektu przez delegowanie pracy do agentów warstwowych.
Ten katalog zawiera też szablony tasków, review i zasady eskalacji, aby przyszłe środowisko CrewAI działało przewidywalnie i bez chaosu.

## Local setup

Lokalne zależności Python dla warstwy agentowej są przypięte w `ai_agents/requirements.txt`.
Powinny być instalowane do projektowego `.venv`, a nie do systemowego Pythona.

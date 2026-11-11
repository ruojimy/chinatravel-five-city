import sys, io
sys.stdout.reconfigure(encoding="utf-8")
from chinatravel.environment.world_env import WorldEnv
env = WorldEnv()
out = env("attractions_types('上海')")
print("attractions_types:", str(out)[:300])
out = env("restaurants_cuisine('广州')")
print("restaurants_cuisine:", str(out)[:300])
out = env("goto('广州','广州塔','珠江新城','10:00','metro')")
print("goto:", str(out)[:400])
out = env("intercity_transport_select('上海','广州','train','08:00')")
print("intercity:", str(out)[:400])

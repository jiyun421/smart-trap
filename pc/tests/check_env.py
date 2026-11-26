"""환경 구축 확인 스크립트."""
import sys
import numpy, pandas, sklearn, matplotlib, seaborn, requests

print("Python      :", sys.version.split()[0])
for m in (numpy, pandas, sklearn, matplotlib, seaborn, requests):
    print(f"{m.__name__:<12}:", m.__version__)

df = pandas.DataFrame({"trap_id": ["T1", "T2"], "detections": [3, 5]})
assert df["detections"].sum() == 8
print("pandas 동작 확인 OK")
print("환경 구축 완료")

from dataclasses import dataclass

@dataclass(frozen=True)
class obj:
    a: int
    b: int

x = obj(1,2)
y = obj(1,2)
c = {y:1, 2:2}
print(x in c)
# True


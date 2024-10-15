from dataclasses import dataclass

class obj:
    def __init__(self,a,b):
        self.a = a
        self.b = b

x = obj(1,2)
y = obj(1,2)
c = {y:1, 2:2}
print(x in c)
# False

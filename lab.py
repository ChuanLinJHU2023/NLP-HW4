class obj:
    def __init__(self,a,b):
        self.a = a
        self.b = b

a = obj(1,2)
b = obj(1,2)
c = [b,5]
print(a in c)

a = [1,2]
b = [1,2]
c = [b,5]
print(a in c)
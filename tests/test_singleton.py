from pyseq2.utils.utils import Singleton


class TestSingleton(metaclass=Singleton): ...


class Meh: ...


def test_singleton():
    assert Meh() is not Meh()
    assert TestSingleton() is TestSingleton()

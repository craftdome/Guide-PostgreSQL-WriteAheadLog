import enum
from datetime import datetime

debug = True


class Log(bytes, enum.Enum):
    INFO = (0, "\033[1;32m")
    WARN = (1, "\033[1;33m")
    ERROR = (2, "\033[1;31m")
    DEBUG = (3, "\033[1;36m")
    FAILOVER = (4, "\033[1;35m")

    def __new__(cls, value, color):
        obj = bytes.__new__(cls, [value])
        obj._value_ = value
        obj.color = color
        return obj

    def print(self, *msgs, sep=' ', end="\r\n", timestamp=True):
        if not (Log.DEBUG == self and not debug):
            msgs = [
                str(msg)
                    .replace("StandBy", "\033[0;33mStandBy\033[0m")
                    .replace("Primary", "\033[1;33mPrimary\033[0m")
                for msg in msgs
            ]

            if timestamp:
                print("%s " % datetime.now().strftime("%Y-%m-%d %H:%M:%S"), end="")

            print("[%s%s\033[0m]" % (self.color, self.name), *msgs, sep=sep, end=end)

    @staticmethod
    def print_ok():
        print("\033[32mOK\033[0m")

    @staticmethod
    def print_failed():
        print("\033[31mFAILED\033[0m")

    @staticmethod
    def print_already():
        print("\033[33mALREADY\033[0m")

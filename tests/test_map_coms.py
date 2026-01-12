from pyseq_core.utils import map_coms
from sequencers.test_sequencer import TestCOM

address_dict = {
    "KLOEHNAA": "PumpACOM",
    "KLOEHNBA": "PumpBCOM",
    "VICIA": "ValveACOM",
    "VICIB": "ValveBCOM",
    "ILXstage": "XStageCOM",
    "ILYstage": "YStageCOM",
    "ILZstage": "ZStageCOM",
    "ILFPGA": "FPGACOM",
    "ILRed": "RedLaserCOM",
    "ILGreen": "GreenLaserCOM",
}


def test_map_coms():
    COM_DICT = map_coms(TestCOM, address_dict=address_dict)
    for com in COM_DICT.values():
        assert com.address is not None

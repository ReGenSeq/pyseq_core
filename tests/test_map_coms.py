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
    # print("PumpA", HW_CONFIG["PumpA"]["com"]["address"], "address")
    # print("PumpB", HW_CONFIG["PumpB"]["com"]["address"], "address")
    COM_DICT = map_coms(TestCOM, address_dict=address_dict)
    for instrument, com in COM_DICT.items():
        assert com.address is not None

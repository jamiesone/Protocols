from opentrons import protocol_api
from opentrons.types import Point
import math

metadata = {
    'protocolName': 'Illumina COVIDSeq - Part 3: Amplify cDNA',
    'author': 'Opentrons <protocols@opentrons.com>',
    'apiLevel': '2.13'
}


def run(ctx):

    [num_samples] = get_values(  # noqa: F821
        'num_samples')

    # tuning parameters
    ctx.max_speeds['X'] = 200
    ctx.max_speeds['Y'] = 200

    cdna_plate = ctx.load_labware('nest_96_wellplate_100ul_pcr_full_skirt',
                                  '2', 'cDNA plate')
    reagent_plate = ctx.load_labware('nest_96_wellplate_100ul_pcr_full_skirt',
                                     '5', 'reagent plate')
    cov1_plate = ctx.load_labware('nest_96_wellplate_100ul_pcr_full_skirt',
                                  '6', 'COV1 plate')
    cov2_plate = ctx.load_labware('nest_96_wellplate_100ul_pcr_full_skirt',
                                  '3', 'COV2 plate')
    tips20 = [
        ctx.load_labware('opentrons_96_filtertiprack_20ul', slot,
                         '200µl filtertiprack')
        for slot in ['7']]

    # load P300M pipette
    m20 = ctx.load_instrument(
        'p20_multi_gen2', 'right', tip_racks=tips20)

    # reagents and variables
    mm1 = reagent_plate.rows()[0][2:4]
    mm2 = reagent_plate.rows()[0][4:6]

    vol_mm = 20.0
    vol_cdna = 5.0
    num_cols = math.ceil(num_samples/8)
    ref_well = cdna_plate.wells()[0]
    if ref_well.width:
        radius = ref_well.width/2
    else:
        radius = ref_well.diameter/2

    def wick(pip, well, side=1):
        pip.move_to(well.bottom().move(Point(x=side*radius*0.8, z=3)))

    def slow_withdraw(pip, well):
        ctx.max_speeds['A'] = 25
        ctx.max_speeds['Z'] = 25
        pip.move_to(well.top())
        del ctx.max_speeds['A']
        del ctx.max_speeds['Z']

    def pick_up(pip, spot=None):
        if spot:
            pip.pick_up_tip(spot)
        else:
            try:
                pip.pick_up_tip()
            except protocol_api.labware.OutOfTipsError:
                ctx.pause("\n\n\n\nReplace 200ul filtertipracks before \
resuming.\n\n\n\n")
                pip.reset_tipracks()
                pip.pick_up_tip()

    for mm, cov_plate in zip([mm1, mm2], [cov1_plate, cov2_plate]):
        pick_up(m20)
        for i, d in enumerate(cov_plate.rows()[0][:num_cols]):
            mm_source = mm[i//6]
            m20.aspirate(vol_mm, mm_source.bottom(0.5))
            slow_withdraw(m20, mm_source)
            m20.dispense(vol_mm, d.bottom(0.5))
            wick(m20, d)
        
        for s, d in zip(cdna_plate.rows()[0][:num_cols],
                        cov_plate.rows()[0][:num_cols]):
            if not m20.has_tip:
                pick_up(m20)
            m20.aspirate(vol_cdna, s.bottom(0.5))
            slow_withdraw(m20, s)
            m20.dispense(vol_cdna, d.bottom(2))
            wick(m20, d)
            m20.drop_tip()

    ctx.comment('\n\n\n\nProtocol complete.\nSeal and shake at 1600 rpm for 1 \
minute. Centrifuge at 1000 x g for 1 minute. Place in the preprogrammed \
thermal cycler and run the COVIDSeq PCR program.\n\n\n\n')

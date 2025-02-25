from opentrons.types import Point
import math
import csv
from datetime import date

metadata = {
    'protocolName': '384-Well PCR Prep',
    'author': 'Nick <ndiehl@opentrons.com>',
    'description': 'Custom Protocol Request',
    'apiLevel': '2.13'
}


def run(ctx):

    [num_samples, vol_sample, num_mixes, vol_mix,
     num_replicates, do_plate_mm, do_cool_samples,
     run_id] = get_values(  # noqa: F821
     'num_samples', 'vol_sample', 'num_mixes', 'vol_mix', 'num_replicates',
     'do_plate_mm', 'do_cool_samples', 'run_id')

    if not run_id:
        ctx.pause('\n\n\n\nNo run ID entered. Proceed?\n\n\n\n')

    ctx.max_speeds['X'] = 200
    ctx.max_speeds['Y'] = 200

    # modules
    tempdeck = ctx.load_module('tempdeck', '6')
    if do_cool_samples:
        tempdeck.set_temperature(4)

    # labware

    plate_384_def = 'biorad_384_wellplate_50ul' if ctx.is_simulating() \
        else 'biorad_384_wellplate_50ul'
    distribution_plate = ctx.load_labware(
            'usascientific_96_wellplate_200ul', '1',
            'mix distribution plate')
    plate384 = ctx.load_labware(plate_384_def, '2', 'PCR plate')
    plate96 = tempdeck.load_labware('usascientific_96_aluminumblock_200ul',
                                    'sample plate')
    mix_tuberack = ctx.load_labware(
        'opentrons_24_aluminumblock_generic_2ml_screwcap', '4',
        'mastermix tuberack')

    num_cols_samples = math.ceil(num_samples/8)
    num_racks = math.ceil(
        (num_mixes + (num_cols_samples*num_replicates*num_mixes))/12)
    tipracks_20 = [
        ctx.load_labware('opentrons_96_filtertiprack_20ul', slot)
        for slot in ['5', '7', '8', '9', '10'][:num_racks]]

    # pipettes
    p20 = ctx.load_instrument(
        'p20_single_gen2', 'right', tip_racks=tipracks_20)
    m20 = ctx.load_instrument(
        'p20_multi_gen2', 'left', tip_racks=tipracks_20)

    # reagents and variables
    samples = plate96.rows()[0][:num_cols_samples]
    mix_tubes = mix_tuberack.wells()[:num_mixes]

    all_dests_flattened = [
        well
        for row in plate384.rows()[:2]
        for well in row]
    mix_columns = distribution_plate.columns()[:num_mixes]
    num_dests_per_mix = num_cols_samples*num_replicates
    mix_dest_sets = [
        all_dests_flattened[i*num_dests_per_mix:(i+1)*num_dests_per_mix]
        for i in range(num_mixes)]

    sample_dest_sets = []
    for i in range(num_cols_samples):
        d_set = []
        for m_set in mix_dest_sets:
            little_set = m_set[i*num_replicates:(i+1)*num_replicates]
            for well in little_set:
                d_set.append(well)
        sample_dest_sets.append(d_set)

    ref_well = plate384.wells()[0]
    try:
        radius = ref_well.diameter/2
    except TypeError:
        radius = ref_well.width/2

    def wick(pip, well, side=1):
        pip.move_to(well.bottom().move(Point(x=side*radius*0.7, z=3)))

    def slow_withdraw(pip, well):
        ctx.max_speeds['A'] = 25
        ctx.max_speeds['Z'] = 25
        pip.move_to(well.top())
        del ctx.max_speeds['A']
        del ctx.max_speeds['Z']

    map = {
        well: {
            'sample': None,
            'mix': None
        }
        for well in plate384.wells()
    }

    def map_384_to_source(source, dest, source_is_col=True,
                          source_type='sample'):
        col = plate384.columns()[plate384.wells().index(dest)//16]
        dests_384 = col[col.index(dest)::2]
        if source_is_col:
            source_col = plate96.columns()[plate96.rows()[0].index(source)]
        else:
            source_col = [source]*8

        map_key = source_type
        for source, dest in zip(source_col, dests_384):
            map[dest][map_key] = source

    # plate mixes from tubes
    overage_factor = 1.05
    vol_per_distribution_well = vol_mix*num_cols_samples*(
        num_replicates*overage_factor)
    num_asp = math.ceil(
        vol_per_distribution_well/p20.tip_racks[0].wells()[0].max_volume)
    vol_per_asp = round(vol_per_distribution_well/num_asp, 2)
    for i, (tube, col) in enumerate(zip(mix_tubes, mix_columns)):
        p20.pick_up_tip(p20.tip_racks[0].rows()[0][i])
        for well in col:
            for _ in range(num_asp):
                p20.aspirate(vol_per_asp, tube.bottom(0.5))
                slow_withdraw(p20, tube)
                p20.dispense(vol_per_asp, well.bottom(0.5))
                slow_withdraw(p20, well)
        p20.return_tip()  # save tip corresponding to each mix for next step
    p20.reset_tipracks()

    # distribute mixes
    for tube, column, dest_set in zip(mix_tubes, mix_columns, mix_dest_sets):
        m20.pick_up_tip()
        for d in dest_set:
            map_384_to_source(tube, d, source_is_col=False, source_type='mix')
            m20.aspirate(vol_mix, column[0].bottom(0.8))
            slow_withdraw(m20, column[0])
            m20.dispense(vol_mix, d.bottom(0.8))
            wick(m20, d)
        m20.drop_tip()

    # transfer sample
    for sample, sample_dest_set in zip(samples, sample_dest_sets):
        for d in sample_dest_set:
            map_384_to_source(sample, d)
            m20.pick_up_tip()
            m20.aspirate(vol_sample, sample.bottom(0.8))
            slow_withdraw(m20, sample)
            m20.dispense(vol_sample, d.bottom(0.8))
            # mix
            slow_withdraw(m20, d)
            m20.drop_tip()

    today = date.today()
    datestr = today.strftime('%Y%m%d')
    path = '/var/lib/jupyter/notebooks'
    out_csv_path = f'{path}/{datestr}_{run_id}.csv'

    if not ctx.is_simulating():
        headers = ['384 well', 'sample source well', 'mastermix tube']
        with open(out_csv_path, 'w') as out_file:
            writer = csv.writer(out_file)
            writer.writerow(headers)
            for well384 in plate384.wells():
                info = map[well384]
                final_well = well384.display_name.split(' ')[0]
                if info['sample']:
                    sample96 = info['sample'].display_name.split(' ')[0]
                else:
                    sample96 = None
                if info['mix']:
                    mix = info['mix'].display_name.split(' ')[0]
                else:
                    mix = None
                data_line = [final_well, sample96, mix]
                writer.writerow(data_line)

    tempdeck.deactivate()

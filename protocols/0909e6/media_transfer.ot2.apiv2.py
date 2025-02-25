from io import StringIO
import csv
import math
from opentrons.protocol_api.labware import Well

metadata = {
    'protocolName': 'DOE',
    'author': 'Nick <ndiehl@opentrons.com',
    'source': 'Custom Protocol Request',
    'apiLevel': '2.12'
}


def run(ctx):

    [csv_factors, vol_media_tubes, vol_mix,
     reps_mix] = get_values(  # noqa: F821
        'csv_factors', 'vol_media_tubes', 'vol_mix', 'reps_mix')

    vol_pre_airgap_1000 = 50.0
    vol_pre_airgap_300 = 20.0

    class WellH(Well):
        def __init__(self, well, height=5, min_height=3,
                     comp_coeff=1.15, current_volume=0, min_vol=1000):
            super().__init__(well._impl)
            self.well = well
            self.height = height
            self.min_height = min_height
            self.comp_coeff = comp_coeff
            self.radius = self.diameter/2
            self.current_volume = current_volume
            self.min_vol = min_vol

        def height_dec(self, vol):
            dh = (vol/(math.pi*(self.radius**2)))*self.comp_coeff
            if self.height - dh > self.min_height:
                self.height = self.height - dh
            else:
                self.height = self.min_height
            if self.current_volume - vol > 0:
                self.current_volume = self.current_volume - vol
            else:
                self.current_volume = 0
            return self.well.bottom(self.height)

        def height_inc(self, vol):
            dh = (vol/(math.pi*(self.radius**2)))*self.comp_coeff
            if self.height + dh < self.depth:
                self.height = self.height + dh
            else:
                self.height = self.depth
            self.current_volume += vol
            return self.well.bottom(self.height + 20)

    # labware
    tuberack50 = ctx.load_labware('opentrons_6_tuberack_falcon_50ml_conical',
                                  '1', 'media tuberack')
    tuberacks15 = [
        ctx.load_labware('opentrons_15_tuberack_falcon_15ml_conical',
                         slot, f'factor {factor_ids} tuberack')
        for slot, factor_ids in zip(['4', '7'], ['1-15', '16-30'])]
    plate = ctx.load_labware('usascientific_96_wellplate_2.4ml_deep', '2')
    tiprack300 = [ctx.load_labware('opentrons_96_filtertiprack_200ul', '3')]
    tiprack1000 = [
        ctx.load_labware('opentrons_96_filtertiprack_1000ul', slot)
        for slot in ['6']]

    # pipettes
    p300 = ctx.load_instrument('p300_single_gen2', 'left',
                               tip_racks=tiprack300)
    p1000 = ctx.load_instrument('p1000_single_gen2', 'right',
                                tip_racks=tiprack1000)

    # reagents
    vol_media_list = [float(val) for val in vol_media_tubes.split(',')]
    media_rows_ordered = [tube for row in tuberack50.rows() for tube in row]
    media = [
        WellH(well, current_volume=vol, height=well.depth*(vol/50000)*0.9)
        for well, vol in zip(
            media_rows_ordered[:len(vol_media_list)],
            [vol_media_tube*1000 for vol_media_tube in vol_media_list])]

    # parse data
    f = StringIO(csv_factors)
    reader = csv.reader(f, delimiter=',')
    data = []
    factor_volumes_ml = None
    for i, row in enumerate(reader):
        if i == 1:
            factor_volumes_ml = [float(val) for val in row[1:] if val]
        if i > 1:
            content = [float(val) for val in row if val]
            data.append(content)
    num_factors = len(data[0]) - 1  # exclude media volume

    factor_tubes = [
        well for rack in tuberacks15 for well in rack.wells()][:num_factors]
    factor_heights = [
        # ensure tip is submerged
        round(vol/15*tuberacks15[0].wells()[0].depth*0.9, 1)
        for vol in factor_volumes_ml]
    factors = [
        WellH(well, current_volume=vol*1000, height=height)
        for well, vol, height in zip(
            factor_tubes, factor_volumes_ml, factor_heights)]

    def slow_withdraw(well, pip=p1000):
        ctx.max_speeds['A'] = 25
        ctx.max_speeds['Z'] = 25
        pip.move_to(well.top())
        del ctx.max_speeds['A']
        del ctx.max_speeds['Z']

    def split_media_vol(vol):
        num_transfers = math.ceil(vol/(1000-vol_pre_airgap_1000))
        vol_per_transfer = round(vol/num_transfers, 1)
        return [vol_per_transfer]*num_transfers

    # iterate
    iterator_media = iter(media)
    current_media = next(iterator_media)

    def check_media(vol):
        nonlocal current_media
        if current_media.current_volume - vol < current_media.min_vol:
            current_media = next(iterator_media)

    def custom_distribute(info, pip):
        pip_volume = pip.tip_racks[0].wells()[0].max_volume
        vol_pre_airgap = vol_pre_airgap_300 if pip == \
            p300 else vol_pre_airgap_1000
        max_vol = pip_volume
        sets = []
        running = []
        current_vol = 0
        for d in info:
            well = [key for key in d.keys()][0]
            vol = [val for val in d.values()][0]
            if vol > 0:
                if current_vol + vol + vol_pre_airgap > max_vol:
                    sets.append(running)
                    running = []
                    current_vol = 0
                running.append({well: vol})
                current_vol += vol + vol_pre_airgap_300
        sets.append(running)
        return sets

    # transfer media
    p1000.pick_up_tip()
    wells_ordered = [well for row in plate.rows() for well in row]
    vols_media = [line[0] for line in data]
    media_info = []
    for well, vol_media in zip(wells_ordered, vols_media):
        vols_split = split_media_vol(vol_media)
        for vol in vols_split:
            media_info.append({well: vol})

    media_sets = custom_distribute(media_info, pip=p1000)
    for media_set in media_sets:
        if p1000.current_volume:
            p1000.dispense(p1000.current_volume, current_media.well.top())
        # pre-air_gap to fully void tip on blow_out
        for d in media_set:
            asp_vol = sum(d.values())
            check_media(asp_vol)
            p1000.aspirate(vol_pre_airgap_1000, current_media.well.top())
            p1000.aspirate(asp_vol, current_media.height_dec(asp_vol))
        slow_withdraw(current_media.well, p1000)
        for i, d in enumerate(media_set):
            well = [key for key in d.keys()][0]
            vol = [val for val in d.values()][0]
            p1000.dispense(vol+vol_pre_airgap_1000, well.bottom(well.depth/2))
            if i == len(media_set) - 1:
                p1000.blow_out(well.bottom(well.depth/2))
            slow_withdraw(well, p1000)
    p1000.return_tip()
    p1000.reset_tipracks()

    # transfer factors
    for i, factor in enumerate(factors):
        factor_vols = [line[1+i] for line in data]
        factor_info = [
            {well: vol}
            for well, vol in zip(wells_ordered, factor_vols)]
        factor_sets = custom_distribute(factor_info, pip=p300)
        for factor_set in factor_sets:
            # aspirate total vol needed
            if not p300.has_tip:
                p300.pick_up_tip()
            # pre-air_gap to fully void tip on blow_out
            for d in factor_set:
                p300.aspirate(vol_pre_airgap_300, factor.well.top())
                asp_vol = sum(d.values())
                p300.aspirate(asp_vol, factor.height_dec(asp_vol))
            # total_factor_vol = sum([sum(dict.values()) for dict in
            # factor_set])
            # p300.aspirate(total_factor_vol,
            #               factor.height_dec(total_factor_vol))
            slow_withdraw(factor.well, p300)
            for i, dict in enumerate(factor_set):
                for well, vol in dict.items():
                    p300.dispense(
                            vol+vol_pre_airgap_300, well.bottom(well.depth/2))
                if i == len(factor_set) - 1:
                    p300.blow_out(well.top(-2))
        if p300.has_tip:
            p300.drop_tip()

    # mix
    for well in plate.wells()[:len(data)]:
        p1000.pick_up_tip()
        p1000.mix(reps_mix, vol_mix, well.bottom(2))
        slow_withdraw(well, p1000)
        p1000.drop_tip()

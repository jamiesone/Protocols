from opentrons.protocol_api.labware import OutOfTipsError
from itertools import zip_longest
import csv
import math

metadata = {
    'title': 'Sample Mixing',
    'author': 'Steve Plonk',
    'apiLevel': '2.11'
}


def run(ctx):

    [multitasking, rate_asp_r, rate_disp_r, rate_asp_l, rate_disp_l,
     filter_tips, pip_l, pip_r, labware_1, clearance_1, labware_2, clearance_2,
     labware_3, clearance_3, labware_4, clearance_4, labware_5, clearance_5,
     labware_6, clearance_6, labware_res, labware_11, clearance_11,
     uploaded_csv] = get_values(  # noqa: F821
     "multitasking", "rate_asp_r", "rate_disp_r", "rate_asp_l", "rate_disp_l",
     "filter_tips", "pip_l", "pip_r", "labware_1", "clearance_1", "labware_2",
     "clearance_2", "labware_3", "clearance_3", "labware_4", "clearance_4",
     "labware_5", "clearance_5", "labware_6", "clearance_6", "labware_res",
     "labware_11", "clearance_11", "uploaded_csv")

    ctx.set_rail_lights(True)
    ctx.delay(seconds=10)

    # csv
    tfers = [line for line in csv.DictReader(uploaded_csv.splitlines())]

    # selected pipettes and corresponding tips
    tipmap = {
     'p20_single_gen2': 'opentrons_96_{}tiprack_20ul'.format(
      'filter' if filter_tips else ''),
     'p300_single_gen2': 'opentrons_96_{0}tiprack_{1}00ul'.format(
      'filter' if filter_tips else '', '2' if filter_tips else '3'),
     'p1000_single_gen2': 'opentrons_96_{}tiprack_1000ul'.format(
      'filter' if filter_tips else '')
      }

    slotmap = {
     'opentrons_96_{}tiprack_20ul'.format(
      'filter' if filter_tips else ''): [7],
     'opentrons_96_{0}tiprack_{1}00ul'.format(
      'filter' if filter_tips else '', '2' if filter_tips else '3'): [8],
     'opentrons_96_{}tiprack_1000ul'.format(
      'filter' if filter_tips else ''): [9]
      }

    clearances = {}
    for clearance, name in zip(
     [clearance_1, clearance_2, clearance_3, clearance_4, clearance_5,
      clearance_6, clearance_11],
     ['clearance_1', 'clearance_2', 'clearance_3', 'clearance_4',
      'clearance_5', 'clearance_6', 'clearance_11']):
        if not clearance > 0:
            raise Exception(
             '''Specified well bottom clearances must be greater than 0''')
        clearances[int(name[10:])] = clearance

    loaded = []

    if pip_l:

        # use all three slots when only one pipette
        slots = slotmap.get(tipmap.get(pip_l)) if pip_r else [7, 8, 9]

        tipsleft = [ctx.load_labware(
         tipmap.get(pip_l), str(slot)) for slot in slots]

        pipette_l = ctx.load_instrument(
            pip_l, 'left', tip_racks=tipsleft)

        loaded.append(pipette_l)

        pipette_l.flow_rate.aspirate = rate_asp_l*pipette_l.flow_rate.aspirate
        pipette_l.flow_rate.dispense = rate_disp_l*pipette_l.flow_rate.dispense

    if pip_r:

        # use all three slots when only one pipette
        slots = slotmap.get(tipmap.get(pip_r)) if pip_l else [7, 8, 9]

        if not pip_l == pip_r:

            tipsright = [ctx.load_labware(
             tipmap.get(pip_r), str(slot)) for slot in slots]

        else:

            # when pip_r and pip_l same type, share same tips in 7, 8, 9
            tipsright = []
            tipsright.append(tipsleft[0])
            for key in [7, 8, 9]:
                if key not in ctx.loaded_labwares.keys():
                    new = ctx.load_labware(tipmap.get(pip_r), str(key))
                    tipsright.append(new)
                    tipsleft.append(new)

        pipette_r = ctx.load_instrument(
            pip_r, 'right', tip_racks=tipsright)

        loaded.append(pipette_r)

        pipette_r.flow_rate.aspirate = rate_asp_r*pipette_r.flow_rate.aspirate
        pipette_r.flow_rate.dispense = rate_disp_r*pipette_r.flow_rate.dispense

    # one or two loaded pipettes in volume order
    loaded.sort(key=lambda element: element.max_volume)

    # no unworkable volumes for selected pipettes - otherwise user's discretion
    for tfer in tfers:
        v = float(tfer['Sample_Volume'])
        if not 0.95*loaded[0].min_volume <= v <= 15*loaded[-1].max_volume:
            raise Exception(
             '''Specified {} uL transfer volume
             not workable with selected pipettes'''.format(v))

    # count and list high volume and low volume transfers
    highvol = []
    lowvol = []
    if (pip_l and pip_r):
        if pip_l != pip_r:
            for tfer in tfers:
                vol = float(tfer['Sample_Volume'])

                if loaded[0].max_volume < vol and loaded[-1].min_volume < vol:
                    highvol.append(tfer)
                else:
                    lowvol.append(tfer)

            # load extra boxes of most-frequent tips in free slots
            tiptype = loaded[-1].name if len(
             highvol) >= len(lowvol) else loaded[0].name

            for key in [7, 8, 9]:
                if key not in ctx.loaded_labwares.keys():
                    new = ctx.load_labware(tipmap[tiptype], str(key))
                    for pipette in loaded:
                        if pipette.name == tiptype:
                            pipette._tip_racks.append(new)

    # use tips in slot order
    if pip_r:
        tipsright.sort(key=lambda element: element.parent)

    if pip_l:
        tipsleft.sort(key=lambda element: element.parent)

    # temperature modules with selected labware
    temp = ctx.load_module('temperature module gen2', '1')
    temp2 = ctx.load_module('temperature module gen2', '4')

    if labware_1:
        temp.load_labware(
         labware_1, "Temperature Module")
        temp.set_temperature(4)

    if labware_4:
        temp2.load_labware(
         labware_4, "Temperature Module 2")
        temp.set_temperature(4)

    # selected labware in slots 2-6, 11
    for labwr, slot in zip(
     [labware_2, labware_3, labware_5, labware_6, labware_11],
     [2, 3, 5, 6, 11]):

        if labwr:
            ctx.load_labware(labwr, str(slot), 'labware '+str(slot))

    for tfer in tfers:

        if int(tfer["Sample_Slot"]) not in ctx.loaded_labwares.keys():
            raise Exception(
             '''CSV-specified source slot {}
             does not have loaded labware'''.format(tfer["Sample_Slot"]))

        elif tfer['Sample_Position'] not in [
         well.well_name for well in ctx.loaded_labwares[
          int(tfer["Sample_Slot"])].wells()]:
            raise Exception(
             '''CSV-specified source sample position {0}
             is not valid for labware loaded in slot {1}'''.format(
              tfer["Sample_Position"], tfer["Sample_Slot"]))

        elif int(tfer["Final_Slot"]) not in ctx.loaded_labwares.keys():
            raise Exception(
                 '''CSV-specified destination slot {}
                 does not have loaded labware'''.format(tfer["Final_Slot"]))

        else:
            if tfer['Final_Position'] not in [
             well.well_name for well in ctx.loaded_labwares[
              int(tfer["Final_Slot"])].wells()]:
                raise Exception(
                 '''CSV-specified final position {0}
                 is not valid for labware loaded in slot {1}'''.format(
                  tfer["Final_Position"], tfer["Final_Slot"]))

    # selected reservoir in slot 10
    if labware_res:
        ctx.load_labware(labware_res, '10', 'Reservoir')

    # notify user to replenish tips
    def pick_up_or_refill(self):
        try:
            self.pick_up_tip()
        except OutOfTipsError:
            ctx.pause(
             """Please Refill the {} Tip Boxes
                and Empty the Tip Waste.""".format(self))
            self.reset_tipracks()
            self.pick_up_tip()

    # transfer sample groups

    if (not multitasking or len(loaded) == 1):

        for tfer in tfers:

            vol = float(tfer['Sample_Volume'])

            p = {
             True: loaded[-1]}.get(((
              vol > loaded[0].max_volume) and (vol > loaded[-1].min_volume)),
              loaded[0])

            air_gap_vol = 0.05*p.max_volume

            reps = math.ceil(
             vol / (int(tipmap[p.name].split('_')[-1].replace(
              'ul', '')) - air_gap_vol))

            if reps:
                v = vol / reps

            tipheight_asp = clearances[int(tfer['Sample_Slot'])]

            tipheight_disp = clearances[int(tfer['Final_Slot'])]

            ctx.comment(
                 "{0} performing {1} transfer".format(p, tfer.items()))

            for rep in range(reps):

                pick_up_or_refill(p)

                loc_asp = ctx.loaded_labwares[int(
                 tfer['Sample_Slot'])].wells_by_name()[tfer['Sample_Position']]

                loc_disp = ctx.loaded_labwares[int(
                 tfer['Final_Slot'])].wells_by_name()[tfer['Final_Position']]

                p.aspirate(v, loc_asp.bottom(tipheight_asp))

                # tip touch
                speed_arg = 3.14*loc_asp.diameter
                r = loc_asp.diameter / 2
                radius_arg = (r - 0.5) / r
                p.touch_tip(radius=radius_arg, v_offset=-10, speed=speed_arg)

                p.air_gap(air_gap_vol)

                p.dispense(v+air_gap_vol, loc_disp.bottom(tipheight_disp))
                p.blow_out()

                # tip touch
                speed_arg = 3.14*loc_disp.diameter
                r = loc_disp.diameter / 2
                radius_arg = (r - 0.5) / r
                p.touch_tip(radius=radius_arg, v_offset=-2, speed=speed_arg)

                p.drop_tip()

    else:

        p = loaded[1]
        p2 = loaded[0]

        if pip_l != pip_r:

            for tferhigh, tferlow in zip_longest(highvol, lowvol):

                if tferhigh:
                    vol = float(tferhigh['Sample_Volume'])

                    air_gap_vol = 0.05*p.max_volume

                    reps = math.ceil(vol / (int(tipmap[p.name].split(
                     '_')[-1].replace('ul', '')) - air_gap_vol))

                    if reps:
                        v = vol / reps

                    tipheight_asp = clearances[int(tfer['Sample_Slot'])]

                    tipheight_disp = clearances[int(tfer['Final_Slot'])]

                    ctx.comment(
                     "{0} performing {1} transfer".format(p, tferhigh.items()))
                else:
                    ctx.comment("Higher volume transfers are finished")

                if tferlow:

                    vol2 = float(tferlow['Sample_Volume'])

                    air_gap_vol2 = 0.05*p2.max_volume

                    reps2 = math.ceil(vol2 / (int(tipmap[p2.name].split(
                     '_')[-1].replace('ul', '')) - air_gap_vol2))

                    ctx.comment(" reps2 {}".format(reps2))

                    if reps2:
                        v2 = vol2 / reps2

                    tipheight_asp2 = clearances[int(tfer['Sample_Slot'])]

                    tipheight_disp2 = clearances[int(tfer['Final_Slot'])]

                    ctx.comment(
                     "{0} performing {1} transfer".format(p2, tferlow.items()))

                else:
                    ctx.comment("Lower volume transfers are finished")

                for rep in range(max([reps, reps2])):

                    if (tferhigh and rep < reps):

                        pick_up_or_refill(p)

                        loc_asp = ctx.loaded_labwares[int(
                         tferhigh['Sample_Slot'])].wells_by_name()[
                         tferhigh['Sample_Position']]

                        loc_disp = ctx.loaded_labwares[int(
                         tferhigh['Final_Slot'])].wells_by_name()[
                         tferhigh['Final_Position']]

                    if (tferlow and rep < reps2):

                        pick_up_or_refill(p2)

                        loc_asp2 = ctx.loaded_labwares[int(
                         tferlow['Sample_Slot'])].wells_by_name()[
                         tferlow['Sample_Position']]

                        loc_disp2 = ctx.loaded_labwares[int(
                         tferlow['Final_Slot'])].wells_by_name()[
                         tferlow['Final_Position']]

                    if (tferhigh and rep < reps):

                        p.aspirate(v, loc_asp.bottom(tipheight_asp))

                        # tip touch
                        speed_arg = 3.14*loc_asp.diameter
                        r = loc_asp.diameter / 2
                        radius_arg = (r - 0.5) / r
                        p.touch_tip(
                         radius=radius_arg, v_offset=-10, speed=speed_arg)

                        p.air_gap(air_gap_vol)

                    if (tferlow and rep < reps2):

                        p2.aspirate(v2, loc_asp2.bottom(tipheight_asp2))

                        # tip touch
                        speed_arg = 3.14*loc_asp2.diameter
                        r = loc_asp2.diameter / 2
                        radius_arg = (r - 0.5) / r
                        p2.touch_tip(
                         radius=radius_arg, v_offset=-10, speed=speed_arg)

                        p2.air_gap(air_gap_vol2)

                    if (tferhigh and rep < reps):

                        p.dispense(
                         v+air_gap_vol, loc_disp.bottom(tipheight_disp))
                        p.blow_out()

                        # tip touch
                        speed_arg = 3.14*loc_disp.diameter
                        r = loc_disp.diameter / 2
                        radius_arg = (r - 0.5) / r
                        p.touch_tip(
                         radius=radius_arg, v_offset=-2, speed=speed_arg)

                    if (tferlow and rep < reps2):

                        p2.dispense(
                         v2+air_gap_vol2, loc_disp2.bottom(tipheight_disp2))
                        p2.blow_out()

                        # tip touch
                        speed_arg = 3.14*loc_disp2.diameter
                        r = loc_disp2.diameter / 2
                        radius_arg = (r - 0.5) / r
                        p2.touch_tip(
                         radius=radius_arg, v_offset=-2, speed=speed_arg)

                    if p.has_tip:
                        p.drop_tip()

                    if p2.has_tip:
                        p2.drop_tip()

        else:

            for tfer1, tfer2 in zip_longest(
             [tfer for index, tfer in enumerate(tfers) if not index % 2],
             [tfer for index, tfer in enumerate(tfers) if index % 2]):

                if tfer1:

                    vol = float(tfer1['Sample_Volume'])

                    air_gap_vol = 0.05*p.max_volume

                    reps = math.ceil(
                     vol / (int(tipmap[p.name].split(
                      '_')[-1].replace('ul', '')) - air_gap_vol))

                    if reps:
                        v = vol / reps

                    tipheight_asp = clearances[int(tfer['Sample_Slot'])]

                    tipheight_disp = clearances[int(tfer['Final_Slot'])]

                    ctx.comment(
                     "{0} performing {1} transfer".format(p, tfer1.items()))
                else:
                    ctx.comment("Higher volume transfers are finished")

                if tfer2:

                    vol2 = float(tfer2['Sample_Volume'])

                    p2 = loaded[0]

                    air_gap_vol2 = 0.05*p2.max_volume

                    reps2 = math.ceil(
                     vol2 / (int(tipmap[p2.name].split(
                      '_')[-1].replace('ul', '')) - air_gap_vol2))

                    if reps2:
                        v2 = vol2 / reps2

                    tipheight_asp2 = clearances[int(tfer['Sample_Slot'])]

                    tipheight_disp2 = clearances[int(tfer['Final_Slot'])]

                    ctx.comment(
                     "{0} performing {1} transfer".format(p2, tfer2.items()))
                else:
                    ctx.comment("Lower volume transfers are finished")

                for rep in range(max([reps, reps2])):

                    if (tfer1 and rep < reps):

                        pick_up_or_refill(p)

                        loc_asp = ctx.loaded_labwares[int(
                         tfer1['Sample_Slot'])].wells_by_name()[
                         tfer1['Sample_Position']]

                        loc_disp = ctx.loaded_labwares[int(
                         tfer1['Final_Slot'])].wells_by_name()[
                         tfer1['Final_Position']]

                    if (tfer2 and rep < reps2):

                        pick_up_or_refill(p2)

                        loc_asp2 = ctx.loaded_labwares[int(
                         tfer2['Sample_Slot'])].wells_by_name()[
                         tfer2['Sample_Position']]

                        loc_disp2 = ctx.loaded_labwares[int(
                         tfer2['Final_Slot'])].wells_by_name()[
                         tfer2['Final_Position']]

                    if (tfer1 and rep < reps):

                        p.aspirate(v, loc_asp.bottom(tipheight_asp))

                        # tip touch
                        speed_arg = 3.14*loc_asp.diameter
                        r = loc_asp.diameter / 2
                        radius_arg = (r - 0.5) / r
                        p.touch_tip(
                         radius=radius_arg, v_offset=-10, speed=speed_arg)

                        p.air_gap(air_gap_vol)

                    if (tfer2 and rep < reps2):

                        p2.aspirate(v2, loc_asp2.bottom(tipheight_asp2))

                        # tip touch
                        speed_arg = 3.14*loc_asp2.diameter
                        r = loc_asp2.diameter / 2
                        radius_arg = (r - 0.5) / r
                        p2.touch_tip(
                         radius=radius_arg, v_offset=-10, speed=speed_arg)

                        p2.air_gap(air_gap_vol2)

                    if (tfer1 and (rep < reps)):

                        p.dispense(
                         v+air_gap_vol, loc_disp.bottom(tipheight_disp))
                        p.blow_out()

                        # tip touch
                        speed_arg = 3.14*loc_disp.diameter
                        r = loc_disp.diameter / 2
                        radius_arg = (r - 0.5) / r
                        p.touch_tip(
                         radius=radius_arg, v_offset=-2, speed=speed_arg)

                    if (tfer2 and (rep < reps2)):

                        p2.dispense(
                         v2+air_gap_vol2, loc_disp2.bottom(tipheight_disp2))
                        p2.blow_out()

                        # tip touch
                        speed_arg = 3.14*loc_disp2.diameter
                        r = loc_disp2.diameter / 2
                        radius_arg = (r - 0.5) / r
                        p2.touch_tip(
                         radius=radius_arg, v_offset=-2, speed=speed_arg)

                    if p.has_tip:
                        p.drop_tip()

                    if p2.has_tip:
                        p2.drop_tip()

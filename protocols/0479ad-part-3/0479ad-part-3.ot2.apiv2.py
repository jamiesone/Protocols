import math
from opentrons.protocol_api.labware import OutOfTipsError
from opentrons import types

metadata = {
    'protocolName': '''NEBNext Ultra II RNA Library Prep Kit for Illumina:
    E7770S Section 1 with Poly(A) Isolation using Oligo-dT Beads:
    Part-3 - Bead Purification of Double-Stranded cDNA''',
    'author': 'Steve Plonk <protocols@opentrons.com>',
    'apiLevel': '2.11'
}


def run(ctx):

    # get parameter values from json above
    [sample_count, labware_tempmod, labware_tempmod2, labware_magneticmodule,
     labware_reservoir, deadvol_reservoir, clearance_beadresuspension,
     clearance_reservoir, time_dry, time_engage, height_engage, offset_x
     ] = get_values(  # noqa: F821
      'sample_count', 'labware_tempmod', 'labware_tempmod2',
      'labware_magneticmodule', 'labware_reservoir', 'deadvol_reservoir',
      'clearance_reservoir', 'clearance_beadresuspension', 'time_dry',
      'time_engage', 'height_engage', 'offset_x')

    # for testing
    skip_addbeads = False
    skip_removesup = False
    skip_washes = False
    skip_elute = False
    skip_recover = False

    ctx.set_rail_lights(True)
    ctx.delay(seconds=10)
    if not 8 <= sample_count <= 48:
        raise Exception('Number of samples must be 8-48.')

    # filter tips, p300 multi
    tips300 = [
     ctx.load_labware("opentrons_96_filtertiprack_200ul", str(
      slot)) for slot in [6, 7, 8, 10, 11]]
    p300m = ctx.load_instrument(
        "p300_multi_gen2", 'right', tip_racks=tips300)

    num_cols = math.ceil(sample_count / 8)

    # temperature module with output plate at 4 degrees
    temp = ctx.load_module('Temperature Module', '1')
    output_plate = temp.load_labware(
     labware_tempmod, 'Output Plate at 4 Degrees C')
    temp.set_temperature(4)

    # temperature module in slot 4 empty
    temp2 = ctx.load_module('Temperature Module', '4')

    # comment to sastify linter
    ctx.comment("Loaded {}".format(temp2))

    # magnetic module with mag plate and double stranded cDNA
    mag = ctx.load_module('magnetic module gen2', '9')
    mag_plate = mag.load_labware(
     labware_magneticmodule, 'Magnetic Module Plate - 300 uL PCR Plate')
    mag.disengage()

    # reagent reservoir with beads, te, EtOH, waste
    reagent_reservoir = ctx.load_labware(
     labware_reservoir, '2', 'Reagent Reservoir')
    [beads, tris] = [
     reagent_reservoir.wells_by_name()[well] for well in ['A1', 'A5']]

    etoh = [reagent_reservoir.wells_by_name()[well] for well in ['A7', 'A8']]
    for well in etoh:
        well.liq_vol = 360*num_cols*p300m.channels + deadvol_reservoir

    waste = [
     reagent_reservoir.wells_by_name()[well] for well in [
      'A9', 'A10', 'A11', 'A12']]

    # beads - 144 uL per sample
    beads.liq_vol = 144*num_cols*p300m.channels + deadvol_reservoir

    tris.liq_vol = 53*num_cols*p300m.channels + deadvol_reservoir

    # alert user to reagent volumes needed
    steps200 = 8
    num_20 = 0
    num_200 = math.ceil(
     steps200*num_cols*p300m.channels / 96) if math.ceil(
     steps200*num_cols*p300m.channels / 96) <= 5 else 5
    ctx.comment(
     """\nEnsure tips (20 uL tips - {0} boxes, 200 uL tips - {1} boxes)
     are present on deck\n""".format(num_20, num_200))
    ctx.comment(
     "\nEnsure output plate is placed on the temperature module in slot 4\n")
    ctx.comment("\nEnsure reagents in sufficient volume are present on deck\n")
    ctx.comment(
     "\n{0} double-stranded cDNA samples (80 uL) in {1}\n".format(
      sample_count, mag_plate))
    for volume, reagent, location in zip(
     [math.ceil(beads.liq_vol), math.ceil(tris.liq_vol), [
      well.liq_vol for well in etoh]],
     ['NEBNext Sample Purification Beads', '0.1X TE', '80 Percent EtOH'],
     [beads, tris, etoh]):
        ctx.comment(
         "\n{0} uL {1} in {2}\n".format(
          str(volume), reagent.upper(), location))

    # return liquid height in a well
    def liq_height(well, effective_diameter=None):
        if well.diameter:
            if effective_diameter:
                radius = effective_diameter / 2
            else:
                radius = well.diameter / 2
            csa = math.pi*(radius**2)
        else:
            csa = well.length*well.width
        return well.liq_vol / csa

    def slow_tip_withdrawal(pipette, well_location, to_center=False):
        if pipette.mount == 'right':
            axis = 'A'
        else:
            axis = 'Z'
        ctx.max_speeds[axis] = 10
        if to_center is False:
            pipette.move_to(well_location.top())
        else:
            pipette.move_to(well_location.center())
        ctx.max_speeds[axis] = None

    # notify user to replenish tips
    def pick_up_or_refill(pip):
        try:
            pip.pick_up_tip()
        except OutOfTipsError:
            ctx.pause(
             """Please Refill the {} Tip Boxes
             and Empty the Tip Waste""".format(pip))
            pip.reset_tipracks()
            pip.pick_up_tip()

    ctx.comment("\nSTEP 1.5.2 - 1.5.3 - mix beads with double stranded cDNA\n")

    # add beads to cDNA in 300 uL PCR plate on magnetic module

    if not skip_addbeads:

        for index, column in enumerate(mag_plate.columns()[:num_cols]):

            pick_up_or_refill(p300m)

            # premix beads
            reps = 3 if index else 10

            ht_premixdispense = liq_height(beads) + 3

            for rep in range(reps):
                p300m.aspirate(
                 200, beads.bottom(clearance_reservoir), rate=0.5)
                p300m.dispense(200, beads.bottom(ht_premixdispense), rate=0.5)

            # aspirate beads
            beads.liq_vol -= 144*p300m.channels

            ht = liq_height(beads) - 3 if liq_height(beads) - 3 > 1 else 1

            p300m.aspirate(
             144, beads.bottom(ht), rate=0.5)
            ctx.delay(seconds=1)
            slow_tip_withdrawal(p300m, beads)

            # reservoir tip touch
            p300m.move_to(
             beads.top(-2).move(types.Point(x=beads.length / 2, y=0, z=0)))
            p300m.move_to(beads.top())

            # dispense beads
            p300m.dispense(144, column[0].bottom(8))

            # mix
            for rep in range(10):
                p300m.aspirate(180, column[0].bottom(1), rate=0.5)
                p300m.dispense(180, column[0].bottom(12), rate=0.5)

            # move half vol to other side of plate
            p300m.aspirate(112, column[0].bottom(1), rate=0.5)
            p300m.touch_tip(radius=0.6, v_offset=-2, speed=10)
            p300m.dispense(112, mag_plate.columns()[index+6][0].bottom(1))
            p300m.blow_out(mag_plate.columns()[index+6][0].top())
            p300m.touch_tip(radius=0.6, v_offset=-2, speed=10)

            p300m.drop_tip()

    ctx.comment("\n5 min room temperature\n")
    ctx.delay(minutes=5)

    ctx.comment("\nSTEP 1.5.4 - engage magnets, discard supernatant\n")

    mag.engage(height_from_base=height_engage)
    ctx.delay(minutes=time_engage)

    if not skip_removesup:

        for index, column in enumerate(mag_plate.columns()[:num_cols]):

            pick_up_or_refill(p300m)

            # from left side of plate
            p300m.move_to(column[0].top())
            p300m.air_gap(20)
            p300m.aspirate(40, column[0].bottom(4), rate=0.2)
            p300m.aspirate(
             140, column[0].bottom(3).move(types.Point(
              x={True: -1}.get(not index % 2, 1)*2, y=0, z=0)), rate=0.2)

            p300m.dispense(200, waste[0].top(), rate=2)
            ctx.delay(seconds=1)
            p300m.blow_out(waste[0].top())
            p300m.air_gap(20)
            p300m.drop_tip()

            pick_up_or_refill(p300m)

            # from right side of plate
            p300m.move_to(mag_plate.columns()[index+6][0].top())
            p300m.air_gap(20)
            p300m.aspirate(
             40, mag_plate.columns()[index+6][0].bottom(4), rate=0.2)
            p300m.aspirate(
             140, mag_plate.columns()[index+6][0].bottom(3).move(types.Point(
              x={True: -1}.get(not index % 2, 1)*2, y=0, z=0)), rate=0.2)

            p300m.dispense(200, waste[0].top(), rate=2)
            ctx.delay(seconds=1)
            p300m.blow_out(waste[0].top())
            p300m.air_gap(20)
            p300m.drop_tip()

    ctx.comment("\nSTEP 1.5.5 - 1.5.6 - EtOH wash, repeat\n")

    if not skip_washes:

        for repeat in range(2):

            # add ethanol
            pick_up_or_refill(p300m)
            for index, column in enumerate(mag_plate.columns()[:num_cols]):

                # to column on left side of plate
                etoh[repeat].liq_vol -= 180*p300m.channels
                ht = liq_height(
                 etoh[repeat]) - 3 if liq_height(
                 etoh[repeat]) - 3 > 1 else 1
                if index:
                    p300m.move_to(etoh[repeat].top())
                    p300m.dispense(20, etoh[repeat].top())
                p300m.aspirate(180, etoh[repeat].bottom(ht))
                p300m.air_gap(20)
                p300m.dispense(200, column[0].top())
                ctx.delay(seconds=0.5)
                p300m.blow_out(column[0].top())
                p300m.air_gap(20)

                # to corresponding column on right side of plate
                etoh[repeat].liq_vol -= 180*p300m.channels
                ht = liq_height(
                 etoh[repeat]) - 3 if liq_height(
                 etoh[repeat]) - 3 > 1 else 1
                p300m.move_to(etoh[repeat].top())
                p300m.dispense(20, etoh[repeat].top())
                p300m.aspirate(180, etoh[repeat].bottom(ht))
                p300m.air_gap(20)
                p300m.dispense(200, mag_plate.columns()[index+6][0].top())
                ctx.delay(seconds=0.5)
                p300m.blow_out(mag_plate.columns()[index+6][0].top())
                p300m.air_gap(20)

            ctx.delay(seconds=30)

            # remove sup
            for index, column in enumerate(mag_plate.columns()[:num_cols]):

                if index:
                    pick_up_or_refill(p300m)
                else:
                    p300m.move_to(column[0].top())
                    p300m.dispense(20, column[0].top())

                loc_left = column[0].bottom(2).move(
                 types.Point(x={True: -1}.get(not index % 2, 1)*2, y=0, z=0))

                loc_right = mag_plate.columns()[index+6][0].bottom(2).move(
                 types.Point(x={True: -1}.get(not index % 2, 1)*2, y=0, z=0))

                p300m.aspirate(130, column[0].bottom(4), rate=0.2)
                p300m.aspirate(50, loc_left, rate=0.2)
                p300m.air_gap(20)
                p300m.dispense(200, waste[repeat].top())
                ctx.delay(seconds=0.5)
                p300m.blow_out()
                p300m.air_gap(20)

                p300m.move_to(mag_plate.columns()[index+6][0].top())
                p300m.dispense(20, mag_plate.columns()[index+6][0].top())

                p300m.aspirate(
                 130, mag_plate.columns()[index+6][0].bottom(4), rate=0.2)
                p300m.aspirate(50, loc_right, rate=0.2)
                p300m.air_gap(20)
                p300m.dispense(200, waste[repeat].top())
                ctx.delay(seconds=0.5)
                p300m.blow_out()
                p300m.air_gap(20)

                p300m.drop_tip()

            # complete removal of last wash

            if repeat:
                for index, column in enumerate(mag_plate.columns()[:num_cols]):
                    pick_up_or_refill(p300m)

                    # remove from column on left side of plate
                    p300m.move_to(column[0].top())
                    p300m.move_to(column[0].bottom(4))
                    for clearance in [0.7, 0.4, 0.2, 0]:

                        loc_left = column[0].bottom(clearance).move(
                         types.Point(x={True: -1}.get(
                          not index % 2, 1)*2, y=0, z=0))

                        p300m.aspirate(25, loc_left)

                    # remove from corresponding column on right side of plate
                    p300m.move_to(mag_plate.columns()[index+6][0].top())
                    p300m.move_to(mag_plate.columns()[index+6][0].bottom(4))
                    for clearance in [0.7, 0.4, 0.2, 0]:

                        loc_right = mag_plate.columns()[index+6][0].bottom(
                         clearance).move(types.Point(x={True: -1}.get(
                          not index % 2, 1)*2, y=0, z=0))

                        p300m.aspirate(25, loc_right)

                    p300m.drop_tip()

    ctx.comment("\nSTEP 1.5.7 - let beads air dry\n")

    ctx.delay(minutes=time_dry)

    ctx.comment("\nSTEP 1.5.8 - 1.5.9 - elute\n")

    # add tris

    if not skip_elute:

        mag.disengage()

        # add tris
        for index, column in enumerate(mag_plate.columns()[:num_cols]):

            pick_up_or_refill(p300m)

            p300m.aspirate(26.5, tris.bottom(clearance_reservoir))

            loc_left = column[0].bottom(clearance_beadresuspension).move(
             types.Point(x={True: 1}.get(
              not index % 2, -1)*offset_x, y=0, z=0))

            p300m.dispense(26.5, loc_left, rate=3)
            for rep in range(15):
                clearance_mixdispense = 6 if (
                 rep % 2) else clearance_beadresuspension
                offset_x_mixdispense = 2.5 if rep % 2 else offset_x
                loc_left = column[0].bottom(clearance_mixdispense).move(
                 types.Point(x={True: 1}.get(
                  not index % 2, -1)*offset_x_mixdispense, y=0, z=0))
                p300m.aspirate(21.5, column[0].bottom(1))
                p300m.dispense(21.5, loc_left, rate=3)
            p300m.blow_out(column[0].top())
            p300m.touch_tip(radius=0.6, v_offset=-2, speed=10)
            p300m.drop_tip()

            pick_up_or_refill(p300m)

            p300m.aspirate(26.5, tris.bottom(clearance_reservoir))

            loc_right = mag_plate.columns()[index+6][0].bottom(
             clearance_beadresuspension).move(types.Point(x={True: 1}.get(
              not index % 2, -1)*offset_x, y=0, z=0))

            p300m.dispense(26.5, loc_right, rate=3)
            for rep in range(15):
                clearance_mixdispense = 6 if (
                 rep % 2) else clearance_beadresuspension
                offset_x_mixdispense = 2.5 if rep % 2 else offset_x
                loc_right = mag_plate.columns()[index+6][0].bottom(
                 clearance_mixdispense).move(types.Point(x={True: 1}.get(
                  not index % 2, -1)*offset_x_mixdispense, y=0, z=0))
                p300m.aspirate(21.5, mag_plate.columns()[index+6][0].bottom(1))
                p300m.dispense(21.5, loc_right, rate=3)
            p300m.blow_out(mag_plate.columns()[index+6][0].top())
            p300m.touch_tip(radius=0.6, v_offset=-2, speed=10)
            p300m.drop_tip()

    # recover eluate
    mag.engage(height_from_base=height_engage)
    ctx.delay(minutes=time_engage)

    if not skip_recover:

        for index, column1, column2 in zip(
         [*range(6)][:num_cols],
         mag_plate.columns()[:num_cols],
         output_plate.columns()[:num_cols]):
            pick_up_or_refill(p300m)

            # aspirate from column on left side of plate
            p300m.move_to(column1[0].top())
            p300m.move_to(column1[0].bottom(4))
            p300m.aspirate(
             25, column1[0].bottom(1.5).move(
              types.Point(x={True: -1}.get(
               not index % 2, 1)*2, y=0, z=0)), rate=0.2)

            # aspirate from corresponding column on right side of plate
            p300m.move_to(mag_plate.columns()[index+6][0].top())
            p300m.move_to(mag_plate.columns()[index+6][0].bottom(4))
            p300m.aspirate(
             25, mag_plate.columns()[index+6][0].bottom(1.5).move(
              types.Point(x={True: -1}.get(
               not index % 2, 1)*2, y=0, z=0)), rate=0.2)

            p300m.dispense(50, column2[0].bottom(1))

            p300m.drop_tip()

    mag.disengage()

    ctx.comment(
     "\nfinished - proceed with part-4 end prep and adapter ligation\n")

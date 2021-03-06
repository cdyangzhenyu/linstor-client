from proto.MsgCrtVlmDfn_pb2 import MsgCrtVlmDfn
from proto.MsgDelVlmDfn_pb2 import MsgDelVlmDfn
from proto.MsgLstRscDfn_pb2 import MsgLstRscDfn
from linstor.sharedconsts import API_CRT_VLM_DFN, API_LST_RSC_DFN, API_DEL_VLM_DFN
from linstor.commcontroller import need_communication
from linstor.commands import Commands, ResourceDefinitionCommands
from linstor.utils import SizeCalc, approximate_size_string, namecheck, Table, Output
from linstor.consts import RES_NAME, Color
from linstor.sharedconsts import (
    FLAG_DELETE
)

import re
import sys


class VolumeDefinitionCommands(Commands):

    @staticmethod
    def setup_commands(parser):
        p_new_vol_command = 'create-volume-definition'
        p_new_vol = parser.add_parser(
            p_new_vol_command,
            aliases=['crtvlmdfn'],
            description='Defines a volume with a capacity of size for use with '
            'linstore. If the resource resname exists already, a new volume is '
            'added to that resource, otherwise the resource is created automatically '
            'with default settings. Unless minornr is specified, a minor number for '
            "the volume's DRBD block device is assigned automatically by the "
            'linstor server.')
        p_new_vol.add_argument('-m', '--minor', type=int)
        p_new_vol.add_argument('-d', '--deploy', type=int)
        p_new_vol.add_argument('-s', '--site', default='',
                               help="only consider nodes from this site")
        p_new_vol.add_argument('resource_name', type=namecheck(RES_NAME),
                               help='Name of an existing resource').completer = ResourceDefinitionCommands.completer
        p_new_vol.add_argument(
            'size',
            help='Size of the volume in resource. '
            'The default unit for size is GiB (size * (2 ^ 30) bytes). '
            'Another unit can be specified by using an according postfix. '
            "Linstor's internal granularity for the capacity of volumes is one "
            'Kibibyte (2 ^ 10 bytes). All other unit specifications are implicitly '
            'converted to Kibibyte, so that the actual size value used by linstor '
            'is the smallest natural number of Kibibytes that is large enough to '
            'accommodate a volume of the requested size in the specified size unit.'
        ).completer = VolumeDefinitionCommands.size_completer
        p_new_vol.set_defaults(func=VolumeDefinitionCommands.create)
        p_new_vol.set_defaults(command=p_new_vol_command)

        # remove-volume definition
        p_rm_vol = parser.add_parser(
            'delete-volume-definition',
            aliases=['delvlmdfn'],
            description='Removes a volume definition from the linstor cluster, and removes '
            'the volume definition from the resource definition. The volume is '
            'undeployed from all nodes and the volume entry is marked for removal '
            "from the resource definition in linstor's data tables. After all "
            'nodes have undeployed the volume, the volume entry is removed from '
            'the resource definition.')
        p_rm_vol.add_argument('-q', '--quiet', action="store_true",
                              help='Unless this option is used, linstor will issue a safety question '
                              'that must be answered with yes, otherwise the operation is canceled.')
        p_rm_vol.add_argument('resource_name',
                              help='Resource name of the volume definition'
                              ).completer = ResourceDefinitionCommands.completer
        p_rm_vol.add_argument(
            'volume_nr',
            type=int,
            help="Volume number to delete.")
        p_rm_vol.set_defaults(func=VolumeDefinitionCommands.delete)

        # list volume definitions
        resgroupby = ()
        volgroupby = resgroupby + ('Vol_ID', 'Size', 'Minor')
        vol_group_completer = Commands.show_group_completer(volgroupby, 'groupby')

        p_lvols = parser.add_parser(
            'list-volume-definitions',
            aliases=['list-volume-definition', 'dspvlmdfn', 'display-volume-definitions', 'volume-definitions',
                     'dspvlmdfn'],
            description=' Prints a list of all volume definitions known to linstor. '
            'By default, the list is printed as a human readable table.')
        p_lvols.add_argument('-p', '--pastable', action="store_true", help='Generate pastable output')
        p_lvols.add_argument('-g', '--groupby', nargs='+',
                             choices=volgroupby).completer = vol_group_completer
        p_lvols.add_argument('-R', '--resources', nargs='+', type=namecheck(RES_NAME),
                             help='Filter by list of resources').completer = ResourceDefinitionCommands.completer
        p_lvols.set_defaults(func=VolumeDefinitionCommands.list)

    @staticmethod
    @need_communication
    def create(cc, args):
        p = MsgCrtVlmDfn()
        p.rsc_name = args.resource_name

        vlmdf = p.vlm_dfns.add()
        vlmdf.vlm_size = VolumeDefinitionCommands._get_volume_size(args.size)
        if args.minor is not None:
            vlmdf.vlm_minor = args.minor

        return Commands._create(cc, API_CRT_VLM_DFN, p, args)

    @staticmethod
    @need_communication
    def delete(cc, args):
        p = MsgDelVlmDfn()
        p.rsc_name = args.resource_name
        p.vlm_nr = args.volume_nr

        return Commands._delete_and_output(cc, args, API_DEL_VLM_DFN, [p])

    @staticmethod
    @need_communication
    def list(cc, args):
        lstmsg = Commands._get_list_message(cc, API_LST_RSC_DFN, MsgLstRscDfn(), args)

        if lstmsg:
            tbl = Table(utf8=not args.no_utf8, colors=not args.no_color, pastable=args.pastable)
            tbl.add_column("ResourceName")
            tbl.add_column("VolumeNr")
            tbl.add_column("VolumeMinor")
            tbl.add_column("Size")
            tbl.add_column("State", color=Output.color(Color.DARKGREEN, args.no_color))
            for rsc_dfn in lstmsg.rsc_dfns:
                for vlmdfn in rsc_dfn.vlm_dfns:
                    tbl.add_row([
                        rsc_dfn.rsc_name,
                        vlmdfn.vlm_nr,
                        vlmdfn.vlm_minor,
                        approximate_size_string(vlmdfn.vlm_size),
                        tbl.color_cell("DELETING", Color.RED)
                            if FLAG_DELETE in rsc_dfn.rsc_dfn_flags else tbl.color_cell("ok", Color.DARKGREEN)
                    ])
            tbl.show()

            # prntfrm = "{res:<15s} {uuid:<40s} {vlmnr:<5s} {vlmminor:<10s} {vlmsize:<10s}"
            # print(prntfrm.format(res="Resource", uuid="UUID", vlmnr="VlmNr", vlmminor="VlmMinor", vlmsize="Size"))
            # prntfrm = "{res:<15s} {uuid:<40s} {vlmnr:<5d} {vlmminor:<10d} {vlmsize:<20s}"
            # for rscdfn in lstmsg.rsc_dfns:
            #     for vlmdfn in rscdfn.vlm_dfns:
            #         print(prntfrm.format(
            #             res=rscdfn.rsc_name,
            #             uuid=vlmdfn.vlm_dfn_uuid,
            #             vlmnr=vlmdfn.vlm_nr,
            #             vlmminor=vlmdfn.vlm_minor,
            #             vlmsize=approximate_size_string(vlmdfn.vlm_size)))

        return None

    @classmethod
    def _get_volume_size(cls, size_str):
        m = re.match('(\d+)(\D*)', size_str)

        size = 0
        try:
            size = int(m.group(1))
        except AttributeError:
            sys.stderr.write('Size is not a valid number\n')
            sys.exit(12)

        unit_str = m.group(2)
        if unit_str == "":
            unit_str = "GiB"
        try:
            unit = SizeCalc.UNITS_MAP[unit_str.lower()]
        except KeyError:
            sys.stderr.write('"%s" is not a valid unit!\n' % (unit_str))
            sys.stderr.write('Valid units: %s\n' % (','.join(SizeCalc.UNITS_MAP.keys())))
            sys.exit(12)

        unit = SizeCalc.UNITS_MAP[unit_str.lower()]

        if unit != SizeCalc.UNIT_kiB:
            size = SizeCalc.convert_round_up(size, unit,
                                             SizeCalc.UNIT_kiB)

        return size

    @staticmethod
    def size_completer(prefix, **kwargs):
        choices = SizeCalc.UNITS_MAP.keys()
        m = re.match('(\d+)(\D*)', prefix)

        digits = m.group(1)
        unit = m.group(2)

        if unit and unit != "":
            p_units = [x for x in choices if x.startswith(unit)]
        else:
            p_units = choices

        return [digits + u for u in p_units]

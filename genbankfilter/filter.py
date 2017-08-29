import os
import re
import shutil
import pandas as pd
import numpy as np
from Bio import SeqIO
from Bio import Phylo
from Bio.Phylo.TreeConstruction import _DistanceMatrix
from Bio.Phylo.TreeConstruction import DistanceTreeConstructor
from collections import namedtuple


def get_contigs(fasta, contig_totals):
    """
    Return a list of of Bio.Seq.Seq objects for fasta and calculate
    the total the number of contigs.
    """
    try:
        contigs = [seq.seq for seq in SeqIO.parse(fasta, "fasta")]
        contig_count = len(contigs)
        contig_totals.append(contig_count)
    except UnicodeDecodeError:
        print("{} threw UnicodeDecodeError".format(fasta))

    return contigs, contig_count


def get_assembly_size(contigs, assembly_sizes):
    """
    Calculate the sum of all contig lengths
    """
    contig_lengths = (len(str(seq)) for seq in contigs)
    assembly_size = sum(contig_lengths)
    assembly_sizes.append(assembly_size)
    return assembly_size


def get_N_count(contigs, n_counts):
    """
    Count the number of unknown bases, i.e. all bases that are not in [ATCG]
    """
    N_count = sum([len(re.findall("[^ATCG]", str(seq))) for seq in contigs])
    n_counts.append(N_count)
    return N_count


def get_all_fastas(species_dir, ext="fasta"):
    """
    Returns a generator for every file ending with ext
    """
    fastas = (os.path.join(species_dir, f) for f in os.listdir(species_dir)
              if f.endswith('fasta'))
    return fastas


def generate_stats(species_dir, dmx):
    """
    Generate a data frame containing all of the stats for genomes
    in species_dir.
    """
    fastas = get_all_fastas(species_dir)
    file_names, contig_totals, assembly_sizes, n_counts = [], [], [], []
    for f in fastas:
        name = re.search('(GCA.*)(.fasta)', f).group(1)
        file_names.append(name)
        contigs, contig_count = get_contigs(f, contig_totals)
        get_assembly_size(contigs, assembly_sizes)
        get_N_count(contigs, n_counts)

    SeqDataSet = list(zip(n_counts, contig_totals, assembly_sizes, dmx.mean()))
    stats = pd.DataFrame(
        data=SeqDataSet,
        index=file_names,
        columns=["N_Count", "Contigs", "Assembly_Size", "MASH"],
        dtype="float64")

    return stats


def filter_all(species_dir, stats, tree, filter_ranges):
    """
    This function strings together all of the steps
    involved in filtering your genomes.
    """
    max_n_count, c_range, s_range, m_range = filter_ranges
    criteria_and_franges = criteria_dict(filter_ranges)
    summary = {}
    passed, failed_N_count = filter_Ns(stats, max_n_count)
    color_clade(tree, 'N_Count', failed_N_count.index)
    # TODO: Creating summary dict can prob be it's own function
    summary["N_Count"] = (max_n_count, len(failed_N_count))
    if check_df_len(passed):
        filter_results = filter_contigs(stats, passed, c_range, summary)
        color_clade(tree, 'Contigs', filter_results.failed)
        passed = filter_results.passed
    else:
        print("Filtering based on unknown bases resulted in < 5 genomes.  "
              "Filtering will not commence past this stage.")
    criteria = "Assembly_Size"
    if check_df_len(passed):
        filter_results = filter_med_ad(passed, summary, criteria,
                                       criteria_and_franges)
        color_clade(tree, "Assembly_Size", filter_results.failed)
        passed = filter_results.passed
    else:
        print("Filtering based on {} resulted in < 5 genomes.  "
              "Filtering will not commence past this stage.".format(criteria))
    criteria = "MASH"
    if check_df_len(passed):
        filter_results = filter_med_ad(passed, summary, criteria,
                                       criteria_and_franges)
        color_clade(tree, "Assembly_Size", filter_results.failed)
        passed = filter_results.passed
    else:
        print("Filtering based on {} resulted in < 5 genomes.  "
              "Filtering will not commence past this stage.".format(criteria))
    write_summary(species_dir, summary, filter_ranges)
    style_and_render_trees(species_dir, tree, filter_ranges)
    return passed


def criteria_dict(filter_ranges):
    max_n_count, c_range, s_range, m_range = filter_ranges
    criteria = {}
    criteria["N_count"] = max_n_count
    criteria["Contigs"] = c_range
    criteria["Assembly_Size"] = s_range
    criteria["MASH"] = m_range
    return criteria


def filter_Ns(stats, max_n_count):
    """
    Filter out genomes with too many unknown bases.
    """
    passed = stats[stats["N_Count"] <= max_n_count]
    failed_N_count = stats[stats["N_Count"] >= max_n_count]
    return passed, failed_N_count


def filter_contigs(stats, passed, c_range, summary):

    contigs = passed["Contigs"]
    # Only look at genomes with > 10 contigs to avoid throwing off the
    # Median AD Save genomes with < 10 contigs to add them back in later.
    not_enough_contigs = contigs[contigs <= 10]
    contigs = contigs[contigs > 10]
    # Median absolute deviation
    contigs_med_ad = abs(contigs - contigs.median()).mean()
    contigs_dev_ref = contigs_med_ad * c_range
    contigs = contigs[abs(contigs - contigs.median()) <= contigs_dev_ref]
    # Add genomes with < 10 contigs back in
    contigs = pd.concat([contigs, not_enough_contigs])
    lower = contigs.median() - contigs_dev_ref
    upper = contigs.median() + contigs_dev_ref
    # Avoid returning empty DataFrame when no genomes are removed above
    if len(contigs) == len(passed):
        passed_contigs = passed
        failed_contigs = []
    else:
        failed_contigs = [i for i in passed.index if i not in contigs.index]
        passed_contigs = passed.drop(failed_contigs)
    # TODO: remove summary stuff
    range_str = "{:.0f}-{:.0f}".format(lower, upper)
    summary["Contigs"] = (range_str, len(failed_contigs))
    results = namedtuple("filter_contigs_results", ["passed", "failed"])
    filter_contigs_results = results(passed_contigs, failed_contigs)

    return filter_contigs_results


def filter_med_ad(passed, summary, criteria, criteria_and_franges):
    """
    Filter based on median absolute deviation
    """
    f_range = criteria_and_franges[criteria]
    # Get the median absolute deviation
    med_ad = abs(passed[criteria] - passed[criteria].median()).mean()
    dev_ref = med_ad * f_range
    passed = passed[abs(passed[criteria] - passed[criteria].median()) <=
                    dev_ref]
    failed = passed.index[abs(passed[criteria] - passed[criteria].median()) >=
                          dev_ref].tolist()
    lower = passed[criteria].median() - dev_ref
    upper = passed[criteria].median() + dev_ref
    range_str = '{:.0f}-{:.0f}'.format(lower, upper)
    summary[criteria] = (range_str, len(failed))
    results = namedtuple("filter_results", ["passed", "failed"])
    filter_results = results(passed, failed)
    return filter_results


def check_df_len(df, num=5):
    """
    Verify that df has > than num genomes
    """
    if len(df) > num:
        return True
    else:
        return False


def write_summary(species_dir, summary, filter_ranges):
    """
    Write a summary of the filtering results.
    """
    max_n_count, c_range, s_range, m_range = filter_ranges
    out = 'summary_{}-{}-{}-{}.txt'.format(max_n_count, c_range, s_range,
                                           m_range)
    out = os.path.join(species_dir, out)
    if os.path.isfile(out):
        os.remove(out)
    with open(out, 'a') as f:
        for k, v in summary.items():
            f.write('{}\n'.format(k))
            f.write('Range: {}\n'.format(v[0]))
            f.write('Filtered: {}\n\n'.format(v[1]))


def dmx_to_tree(dmx, species_dir):
    """
    Convert dmx to a nested representation of the
    lower diagonal of the distance matrix. Generate
    a _DistanceMatrix object and construct a tree.
    """
    nw_file = os.path.join(species_dir, 'tree.nw')
    m = dmx.as_matrix()
    names = dmx.index.tolist()
    nested_dmx = nested_matrix(m)
    bio_dmx = _DistanceMatrix(names, nested_dmx)
    # TODO: Remove if exists
    phylip_dmx = os.path.join(species_dir, "dmx.phylip")
    with open(phylip_dmx, "w") as f:
        bio_dmx.format_phylip(f)
    constructor = DistanceTreeConstructor()
    tree = constructor.nj(bio_dmx)
    Phylo.write(tree, nw_file, 'newick')
    # TODO: Move reading/reading of tree outside of this function
    # ssould not have to reconstruct tree everytime filtering is run
    tree = read_nw_tree(nw_file)
    tree = base_node_style(tree)
    return tree


def read_nw_tree(nw_file):
    from ete3 import Tree
    tree = Tree(nw_file, 1)
    return tree


def estimate_tree_constructor_runtime(n):
    """
    Estimate the runtime for generating a tree of len n
    """
    from string import ascii_uppercase, digits
    from random import choice
    names = []
    for x in range(n):
        choices = ascii_uppercase + digits
        name = ''.join(choice(choices) for _ in range(10))
        names.append(name)

    nested_dmx = nested_matrix(np.random.rand(n, n))
    bio_dmx = _DistanceMatrix(names, nested_dmx)
    constructor = DistanceTreeConstructor()
    tree = constructor.nj(bio_dmx)
    return tree


def nested_matrix(matrix):
    """
    Create a nested representation of the
    lower triangular matrix
    """
    trild = np.tril(matrix, k=0)
    nested_dmx = []
    mx_len = len(trild)
    for i in np.arange(0, mx_len):
        tmp = trild[i, :i + 1]
        nested_dmx.append(tmp.tolist())
    return nested_dmx


def style_and_render_trees(species_dir, tree, filter_ranges):
    from ete3 import TreeStyle
    max_n_count, c_range, s_range, m_range = filter_ranges
    out = 'tree_{}-{}-{}-{}'.format(max_n_count, c_range, s_range, m_range)
    ts = TreeStyle()
    ts.branch_vertical_margin = 10
    ts.show_leaf_name = False
    tree.render(os.path.join(species_dir, '{}.png'.format(out)), tree_style=ts)
    tree.render(os.path.join(species_dir, '{}.svg'.format(out)), tree_style=ts)
    tree.render(os.path.join(species_dir, '{}.pdf'.format(out)), tree_style=ts)


def base_node_style(tree):
    from ete3 import NodeStyle, AttrFace
    nstyle = NodeStyle()
    nstyle["shape"] = "sphere"
    nstyle["size"] = 2
    nstyle["fgcolor"] = "black"
    for n in tree.traverse():
        n.set_style(nstyle)
        n.add_face(AttrFace('name', ftype='Arial', fsize=8), column=0)
    return tree


def color_clade(tree, criteria, to_color):
    """Color nodes using ete3
    """
    from ete3 import NodeStyle

    colors = {
        "N_Count": "red",
        "Contigs": "green",
        "MASH": "blue",
        "Assembly_Size": "yellow"
    }

    for genome in to_color:
        n = tree.get_leaves_by_name(genome).pop()
        nstyle = NodeStyle()
        nstyle["fgcolor"] = colors[criteria]
        nstyle["size"] = 5
        n.set_style(nstyle)


def stats_and_filter(species_dir, dmx, filter_ranges):
    stats = generate_stats(species_dir, dmx)
    stats.to_csv(os.path.join(species_dir, 'stats.csv'))
    tree = dmx_to_tree(dmx, species_dir)
    results = filter_all(species_dir, stats, tree, filter_ranges)
    passed_final = results
    passed_final.to_csv(os.path.join(species_dir, 'passed.csv'))


def read_dmx(species_dir):
    dmx = os.path.join(species_dir, 'dmx.txt')
    dmx = pd.read_csv(dmx, index_col=0, sep="\t")
    return dmx


# TODO: Put tree stuff in different function
def filter_only(species_dir, filter_ranges):
    from ete3 import Tree
    stats = os.path.join(species_dir, 'stats.csv')
    stats = pd.read_csv(stats, index_col=0)
    nw_file = os.path.join(species_dir, 'tree.nw')
    tree = Tree(nw_file, 1)
    tree = base_node_style(tree)
    results = filter_all(species_dir, stats, tree, filter_ranges)
    passed_final = results
    passed_final.to_csv(os.path.join(species_dir, 'passed.csv'))


def assess_fastas(fasta_dir):

    # Check for empty FASTA's and move them before running MASH
    info = os.path.join(fasta_dir, "info")
    empty = os.path.join(info, "corrupt_fastas")
    for f in os.listdir(fasta_dir):
        if f.endswith("fasta") and os.path.getsize(
                os.path.join(fasta_dir, f)) == 0:
            print("{} is empty and will be moved to {} before runing MASH.".
                  format(f, empty))
            if not os.path.isdir(empty):
                os.mkdir(empty)
            src = os.path.join(fasta_dir, f)
            dst = os.path.join(empty, f)
            shutil.move(src, dst)


def check_passed_dir(species_dir):
    passed_dir = os.path.join(species_dir, "passed")
    if os.path.isdir(passed_dir):
        shutil.rmtree(passed_dir)
    os.mkdir(passed_dir)
    return passed_dir


def min_fastas_check(species_dir):
    """
    Check if speices_dir contains at least 5 FASTAs
    """
    if len(os.listdir(species_dir)) <= 5:
        return False
    return True


def link_passed_genomes(species_dir, passed_final, passed_dir):
    for genome in passed_final.index:
        fasta = "{}.fasta".format(genome)
        # glob_pattern = "{}*fasta".format(genome)
        # fasta = glob.glob(os.path.join(species_dir, glob_pattern))[0]
        # fasta = fasta.split('/')[-1]
        src = os.path.join(species_dir, fasta)
        dst = os.path.join(passed_dir, fasta)
        os.link(src, dst)


# Move to config
def clean_up(species_dir):

    sketch_file = os.path.join(species_dir, "all.msh")
    dmx = os.path.join(species_dir, "dmx.csv")
    filter_log = os.path.join(species_dir, "filter_log.txt")

    info = os.path.join(species_dir, "info")
    if not os.path.isdir(info):
        os.mkdir(info)

    files = [sketch_file, dmx, filter_log]
    for f in files:
        if os.path.isfile(f):
            os.remove(f)

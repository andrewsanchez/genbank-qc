import pandas as pd
from Bio import Entrez


from logbook import Logger
# from retrying import retry

import xml.etree.cElementTree as ET
# from xml.etree.ElementTree import ParseError


ONE_MINUTE = 60000


class Metadata:
    def __init__(self):
        self.log = Logger("Metadata")


class BioSample:
    """Download and parse BioSample metadata for GenBank bacteria genomes."""

    attributes = [
        "BioSample", "geo_loc_name", "collection_date", "strain",
        "isolation_source", "host", "collected_by", "sample_type",
        "sample_name", "host_disease", "isolate", "host_health_state",
        "serovar", "env_biome", "env_feature", "ref_biomaterial",
        "env_material", "isol_growth_condt", "num_replicons",
        "sub_species", "host_age", "genotype", "host_sex", "serotype",
        "host_disease_outcome",
        ]

    def __init__(self):
        """Download and parse BioSample metadata"""
        self.df = pd.DataFrame(index=['BioSample'], columns=self.attributes)

    # @retry(stop_max_attempt_number=3, stop_max_delay=10000, wait_fixed=100)
    def _esearch(self, email='inbox.asanchez@gmail.com', db="biosample",
                 term="bacteria[orgn] AND biosample_assembly[filter]"):

        """Use NCBI's esearch to make a query"""

        Entrez.email = email
        esearch_handle = Entrez.esearch(db=db, term=term, usehistory='y')
        self.esearch_results = Entrez.read(esearch_handle)

    def _efetch(self):
        """Use NCBI's efetch to download esearch results"""
        web_env = self.esearch_results["WebEnv"]
        query_key = self.esearch_results["QueryKey"]
        count = int(self.esearch_results["Count"])
        batch_size = 10000

        self.data = []
        db_xp = 'Ids/Id/[@db="{}"]'
        # Tuples for building XPath patterns
        xp_tups = [('SRA', 'db', db_xp), ('BioSample', 'db', db_xp)]
        for attrib in self.attributes:
            xp_tups.append((attrib, 'harmonized_name',
                            'Attributes/Attribute/[@harmonized_name="{}"]'))

        def parse_record(xml):
            data = {}
            tree = ET.fromstring(xml)
            for attrib, key, xp in xp_tups:
                e = tree.find(xp.format(attrib))
                if e is not None:
                    name = e.get(key)
                    attribute = e.text
                    data[name] = attribute
            self.data.append(pd.DataFrame(data, index=[data['BioSample']]))

        for start in range(0, count, batch_size):
            end = min(count, start+batch_size)
            print("Downloading record {} to {}".format(start+1, end))
            with Entrez.efetch(db="biosample", rettype='docsum',
                               webenv=web_env, query_key=query_key,
                               retstart=start, retmax=batch_size) as handle:
                try:
                    efetch_record = Entrez.read(handle, validate=False)
                except Entrez.Parser.CorruptedXMLError:
                    continue
                    # log here
            for xml in efetch_record['DocumentSummarySet']['DocumentSummary']:
                xml = xml['SampleData']
                parse_record(xml)

    def _DataFrame(self):
        self.file_ = "biosample.csv"
        self.df = pd.concat(self.data)
        self.df.set_index("BioSample", inplace=True)
        self.df.to_csv(self.file_)

    def generate(self):
        self._esearch()
        self._efetch()
        self._DataFrame()


class SRA:
    def __init__(self, args):
        "docstring"
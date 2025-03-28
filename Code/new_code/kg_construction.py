from itertools import combinations
from openai import OpenAI
import os
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
from tqdm import tqdm
import ast

class KGConstruction:
    def __init__(self, **constructor_config) -> None:
        # API_base
        self.API_Base = constructor_config["OpenAI_API_Base"]
        # API_key
        self.key_list = constructor_config["API_key_list"]
        # Model name
        self.model_name = "gpt-4o-2024-08-06"
        # all_file_path
        self.all_file_path = constructor_config["all_file_path"]
        # prompt_path
        self.entity_extratction_prompt_path = constructor_config["kc_entity_extratction_prompt"]
        self.relation_extratction_prompt_path = constructor_config["kc_relation_extratction_prompt"]
        # type_path
        self.entity_type_path = constructor_config["save_ke_entity_type_path"]
        self.relation_type_path = constructor_config["save_ke_relation_type_path"]
        # save path
        self.entity_file_path = constructor_config["save_kc_entity_path"]
        self.relation_file_path = constructor_config["save_kc_relation_path"]
        self.save_kg_schema_path = constructor_config["save_kg_schema_path"]

    def load_message(self, prompt_content):
        instruct_content = "Please complete the task."
        message = [{"role": "system", "content": instruct_content}]
        message.append({"role": "user", "content": prompt_content})
        return message

    def call_llm(self, llm_input, api_key):
        client = OpenAI(api_key=api_key, base_url=self.API_Base)
        response = client.chat.completions.create(
            model=self.model_name,
            messages=llm_input,
            temperature=0,
            max_tokens=4096
        )
        return response.choices[0].message.content.strip().lower()

    def load_existing_schema(self):
        existing_schema_triples = set()
        save_kg_schema_path = self.save_kg_schema_path


        if os.path.exists(save_kg_schema_path):
            try:
                with open(save_kg_schema_path, mode='r', encoding='utf-8') as csvfile:
                    reader = csv.reader(csvfile)
                    next(reader, None)
                    for row in reader:
                        if len(row) == 3:

                            existing_schema_triples.add(tuple(map(str.strip, row)))
            except Exception as e:
                print(f"Failed to read existing KG Schema: {e}")

        return existing_schema_triples

    def read_all_files(self):
        # check seed_path
        if os.path.isdir(self.all_file_path):
            files = os.listdir(self.all_file_path)
            files_list = [os.path.join(self.all_file_path, file) for file in files]
        else:
            files_list = []
            print("Invalid seed path")
        # read file_content
        file_content_list = []
        for path in files_list:
            try:
                with open(path, 'r', encoding='utf-8') as file:
                    reader = csv.reader(file)
                    result = list(reader)
                    for i in range(len(result)):
                        file_content_list.append(result[i][0])
            except Exception as e:
                print(e)
        return file_content_list

    import csv
    def get_entity_type(self):
        entity_type_list = []
        with open(self.entity_type_path, newline='', encoding='utf-8') as csvfile:
            reader = csv.reader(csvfile)
            for row in reader:
                if len(row) >= 3:
                    entity_type_list.append({row[0]: row[2]})
        result_dict = {}
        for item in entity_type_list:
            result_dict.update(item)

        entity_type_str = '\n'.join([f"'{k}': '{v}'" for k, v in result_dict.items()])
        return entity_type_str
    def entity_extraction(self, chunk, entity_type_str, api_key, index):
        try:
            # entity_type_str = self.get_entity_type()
            prompt_content = open(self.entity_extratction_prompt_path, 'r', encoding='utf-8').read()
            prompt_content = prompt_content.replace("${text}$", '"' + chunk + '"').replace("${entity types and their definitions}$", '\n' + entity_type_str)
            llm_input = self.load_message(prompt_content)
            entity_result = self.call_llm(llm_input, api_key)
            if ":" in entity_result:
                entities = entity_result.split("\n")[1]
            else:
                entities = ""
        except:
            entities = ""
        return index, entities

    def save_extracted_entities(self, chunk_list, entity_list, entity_pair_list, save_path):
        result = []
        for idx in range(len(chunk_list)):
            task = {
                "chunk": chunk_list[idx],
                "entities": entity_list[idx],
                "entity_pair": entity_pair_list[idx],
            }
            result.append(task)
        return result

    def process_entity_extraction(self, chunk_list, entity_type_str, save_path):
        all_result = []
        entity_list = [None] * len(chunk_list)
        entity_pair_list = [None] * len(chunk_list)
        with ThreadPoolExecutor(max_workers=len(self.key_list)) as executor:
            futures = {
                executor.submit(self.entity_extraction, chunk, entity_type_str,
                                self.key_list[idx % len(self.key_list)], idx): idx for idx, chunk in
                enumerate(chunk_list)
            }
            for future in tqdm(as_completed(futures), desc="Entity Extraction", total=len(futures)):
                try:
                    index, entities = future.result()
                    entity_list[index] = entities
                    entity_split_list = [item.split(": ")[0].strip() for item in entities.split("; ")]
                    entity_pair_list[index] = list(combinations(entity_split_list, 2))
                    result = self.save_extracted_entities(
                        [chunk_list[index]], [entity_list[index]], [entity_pair_list[index]], save_path
                    )
                    all_result.extend(result)
                except Exception as e:
                    print(f"Error processing chunk at index {index}: {e}")
        df = pd.DataFrame(all_result)
        all_columns = df.columns.tolist()
        df = df[all_columns[:3]]
        df.to_csv(save_path, index=False, header=False)

    def get_relation_type(self):
        relation_type_list = []
        with open(self.relation_type_path, newline='', encoding='utf-8') as csvfile:
            reader = csv.reader(csvfile)
            for row in reader:
                relation_type_list.append({row[0]: row[1]})
        result_dict = {}
        for item in relation_type_list:
            result_dict.update(item)
        relation_type_str = '\n'.join([f"'{k}': '{v}'" for k, v in result_dict.items()])
        return relation_type_str

    import ast

    def relation_extraction(self, chunk, relation_type_str, entity_pair, api_key, index):
        try:

            if isinstance(entity_pair, str):
                entity_pair = ast.literal_eval(entity_pair)

            if entity_pair and entity_pair != "[]":

                entity_pair_str = "; ".join([f"({a}, {b})" for a, b in entity_pair])


                prompt_content = open(self.relation_extratction_prompt_path, 'r', encoding='utf-8').read()
                prompt_content = prompt_content.replace("${text}$", '"' + chunk + '"')
                prompt_content = prompt_content.replace("${entity pairs}$", entity_pair_str)
                prompt_content = prompt_content.replace("${relation types and their definitions}$",
                                                        "\n" + relation_type_str.lower())


                print(f"Generated prompt for relation extraction:\n{prompt_content}")


                llm_input = self.load_message(prompt_content)
                relation_result = self.call_llm(llm_input, api_key)


                print(f"LLM relation extraction result for index {index}:\n{relation_result}")


                relations = relation_result.split("\n")[1:]
                if not relations or all(not rel.strip() for rel in relations):

                    relations = ["No relations extracted"]
                else:

                    valid_relations = []
                    for rel in relations:
                        try:
                            relation_type, entity_triplet = rel.split(": ", 1)

                            if entity_triplet.startswith('(') and entity_triplet.endswith(')'):
                                new_entity_triple = entity_triplet[1:-1]
                                entity1, relation_name, entity2 = new_entity_triple.split(", ")
                                valid_relations.append(f"{relation_type}: ({entity1}, {relation_name}, {entity2})")
                            else:
                                raise ValueError("Invalid entity triplet format")
                        except ValueError as e:
                            print(f"Error parsing relation at index {index}: {e}")
                            continue

                    relations = valid_relations
            else:

                relations = ["No entity pairs provided"]
        except Exception as e:

            print(f"Error extracting relations for index {index}: {e}")
            relations = [f"Error extracting relations: {str(e)}"]


        return index, relations

    def convert2_relation_triples(self, entity_list, relation_list):

        existing_schema_triples = self.load_existing_schema()

        final_output_list = []
        for entities_str, relations in zip(entity_list, relation_list):
            entity_type_mapping = {}
            entities = entities_str.split('; ')
            for entity in entities:
                if entity:
                    entity_name, entity_type = entity.split(': ')
                    entity_type_mapping[entity_name] = entity_type

            output_per_relation = []
            for relation in relations:
                relation_type, entity_triplet = relation.split(': ')
                if entity_triplet.startswith('(') and entity_triplet.endswith(')'):
                    new_entity_triple = entity_triplet[1:-1]
                else:
                    new_entity_triple = entity_triplet

                entity1, relation_name, entity2 = new_entity_triple.split(', ')
                type1 = entity_type_mapping.get(entity1, "unknown").replace(";", "")
                type2 = entity_type_mapping.get(entity2, "unknown").replace(";", "")
                type_triple = (type1, relation_type, type2)


                if type_triple in existing_schema_triples:
                    instance_triple = f"({entity1}, {relation_name}, {entity2})"
                    output_per_relation.append(f"{type_triple}: {instance_triple}")
                else:
                    print(f"Filtered out invalid triple: {type_triple}")

            final_output_list.append(output_per_relation)

        return final_output_list

    def save_extracted_relations(self, chunk_list, entity_list, relation_list):
        result = []
        triple_with_type = self.convert2_relation_triples(entity_list, relation_list)
        for idx in range(len(chunk_list)):
            task = {
                "chunk": chunk_list[idx],
                "relations": relation_list[idx],
                "relation_with_type": triple_with_type[idx],
            }
            result.append(task)
        return result

    def process_relation_extraction(self, chunk_list, relation_type_str, entity_list, entity_pair_list, save_path):
        all_result = []
        relation_list = [None] * len(chunk_list)

        with ThreadPoolExecutor(max_workers=len(self.key_list)) as executor:
            futures = {
                executor.submit(
                    self.relation_extraction, chunk, relation_type_str, entity_pair,
                    self.key_list[idx % len(self.key_list)], idx): idx for idx, (chunk, entity_pair) in
                enumerate(zip(chunk_list, entity_pair_list))
            }

            for future in tqdm(as_completed(futures), desc="Relation Extraction", total=len(futures)):
                try:
                    index, relation_triples = future.result()
                    relation_list[index] = relation_triples


                    result = self.save_extracted_relations(
                        [chunk_list[index]], [entity_list[index]], [relation_list[index]]
                    )
                    all_result.extend(result)
                except Exception as e:
                    print(f"Error processing relation at index {index}: {e}")
                    all_result.extend([{"chunk": chunk_list[index], "relations": "", "relation_with_type": "[]"}])

        df = pd.DataFrame(all_result)
        df.to_csv(save_path, index=False, header=False)
        return relation_list


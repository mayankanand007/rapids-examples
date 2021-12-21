from cudf.core.subword_tokenizer import SubwordTokenizer
import torch
from transformers import AutoModel
from torch.utils.data import TensorDataset, DataLoader

# Vocabulary is included in the root directory of this repo
# however, below is the command to modify / update it -->
# from cudf.utils.hash_vocab_utils import hash_vocab
# hash_vocab('vocab.txt', 'voc_hash.txt')

device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")

# Mean Pooling - Take attention mask into account for correct averaging
def mean_pooling(model_output, attention_mask):
    """Function to implement mean pooling on top of the AutoModel
    See: https://www.sbert.net/examples/applications/computing-embeddings/README.html#sentence-embeddings-with-transformers

    Args:
        model_output \
            (transformers.BaseModelOutputWithPoolingAndCrossAttentions): BERT model
        attention_mask (torch.Tensor): torch.Tensor representing attention
        mask values

    Returns:
        [torch.Tensor]: correct averaging of attention mask
    """
    # First element of model_output contains all token embeddings
    token_embeddings = model_output[0]
    input_mask_expanded = (
        attention_mask.unsqueeze(-1).expand(token_embeddings.size()).float()
    )
    sum_embeddings = torch.sum(token_embeddings * input_mask_expanded, 1)
    sum_mask = torch.clamp(input_mask_expanded.sum(1), min=1e-9)
    return sum_embeddings / sum_mask


def create_embeddings(sentences):
    """Creates the sentence embeddings using SentenceTransformer

    Args:
        sentences (cudf.Series[str]): a cuDF Series of Input strings

    Returns:
        embeddings (cupy.ndarray): corresponding sentence
        embeddings for the strings passed
    """

    cudf_tokenizer = SubwordTokenizer("vocab/voc_hash.txt", do_lower_case=True)

    # Tokenize sentences
    encoded_input_cudf = cudf_tokenizer(
        sentences,
        max_length=128,
        max_num_rows=len(sentences),
        padding="max_length",
        return_tensors="pt",
        truncation=True,
    )

    # Load AutoModel from huggingface model repository
    model_gpu = AutoModel.from_pretrained("sentence-transformers/all-MiniLM-L6-v2").to(
        device
    )

    # Delete the key and associated values we do not need
    del encoded_input_cudf["metadata"]

    batch_size = 64

    dataset = TensorDataset(
        encoded_input_cudf["input_ids"], encoded_input_cudf["attention_mask"]
    )

    dataloader = DataLoader(dataset, batch_size=batch_size)

    del encoded_input_cudf["input_ids"], encoded_input_cudf["attention_mask"]

    pooling_output_ls = []
    with torch.no_grad():
        for b_input_ids, b_attention_mask in dataloader:
            model_obj = model_gpu(
                **{"input_ids": b_input_ids, "attention_mask": b_attention_mask}
            )
            pooling_output_ls.append(mean_pooling(model_obj, b_attention_mask))

    pooling_output = torch.cat(pooling_output_ls)

    return pooling_output
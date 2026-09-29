use crate::document::Document;

pub fn merge_documents(documents: &[Document]) -> String {
    let mut output = String::new();

    for document in documents {
        output.push_str(&format!(
            "\n<!-- Source: {} -->\n\n",
            document.path.display()
        ));

        output.push_str(&document.content);
        output.push_str("\n\n");
    }

    output.trim().to_string()
}

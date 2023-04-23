from chatsnack import Text
from chatsnack.packs import Confectioner

def main():
    default_recipe = """
    Ingredients:
    - 1 cup sugar
    - 1 cup all-purpose flour
    - 1/2 cup unsweetened cocoa powder
    - 3/4 teaspoon baking powder
    - 3/4 teaspoon baking soda
    - 1/2 teaspoon salt
    - 1 large egg
    - 1/2 cup whole milk
    - 1/4 cup vegetable oil
    - 1 teaspoon vanilla extract
    - 1/2 cup boiling water
    """
    recipe_text = Text.objects.get_or_none("RecipeSuggestion")
    if recipe_text is None:
        recipe_text = Text("RecipeSuggestion", default_recipe)
        recipe_text.save()

    recipe_chat = Confectioner.user("Consider the following recipe for a chocolate cake:")

    print(f"Original Recipe: {recipe_text.content}\n\n")
    recipe_chat.user("{text.RecipeSuggestion}")
    recipe_chat.user("Time to remix things! Write a paragraph about the potential of these specific ingredients to make other clever baking possibilities. After that, use the best of those ideas to remix these ingredients for a unique and delicious dessert (include a detailed list of ingredients and steps like a cookbook recipe).")
    remixed_recipe = recipe_chat.chat()
    print(f"Remixed Recipe: \n{remixed_recipe.response}\n")

    # now we want to ask the same expert to review the recipe and give themselves feedback.
    critic_chat = Confectioner.user("Consider the following recipe explanation:")
    critic_chat.user(remixed_recipe.response)
    critic_chat.engine = "gpt-4"   # upgrade the AI for the critic
    critic_chat.user("Thoroughly review the recipe with critical expertise and identify anything you might change. Start by (1) summarizing the recipe you've been given, then (2) write a detailed review of the recipe.")
    critic_response = critic_chat.chat()
    print(f"Recipe Review: \n{critic_response.response}\n")

    # now we feed the review back to the original AI and get them to remedy their recipe with that feedback
    remixed_recipe.user("Write a final full recipe (including ingredients) based on the feedback from this review, giving it a gourmet title and a blog-worthy summary.")
    remixed_recipe.user(critic_response.response)
    final_recipe = remixed_recipe.chat()    
    print(f"Final Recipe: \n{final_recipe.response}\n")

if __name__ == "__main__":
    main()
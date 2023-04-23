$(document).ready(function () {
    let num_tests = 0;
    let currentTest = 0;
    let results = [];
    let completed = 0;

    $("#responseContainer").hide();
    $("#resultsContainer").hide();

    $("#testForm").submit(function (event) {
        event.preventDefault();
        $("#loadingMessage").show();
        num_tests = parseInt($("#num_tests").val());
        if (num_tests > 0) {
            $.post("/start-generation", { num_tests: num_tests })
                .done(() => {
                    fetchResults();
                })
                .fail((error) => {
                    console.error("Error starting text generation:", error);
                });
        }
    });

    function showNextResult() {
        if (currentTest < results.length) {
            $("#loadingMessage").hide();
            $("#responseText").text(results[currentTest].text);
            $("#testForm").hide();
            $("#responseContainer").show();
        } else if (completed === 0) {
            $("#loadingMessage").show();
            $("#testForm").hide();
        } else {
            $("#loadingMessage").hide();
            $("#responseContainer").hide();
            displayResults();
        }
    }

    function updateResultsCounter() {
        $("#resultsCounter").text("Generations created: " + results.length );
    }

    function displayResults() {
        let votes = {};
        for (let result of results) {
            if (!votes.hasOwnProperty(result.generator_name)) {
                votes[result.generator_name] = { votes: 0, texts: [] };
            }
            votes[result.generator_name].votes += result.votes;
            votes[result.generator_name].texts.push(result.text);
        }
    
        let sortedVotes = Object.entries(votes).sort((a, b) => b[1].votes - a[1].votes);
        let winner = sortedVotes[0][0];
        let margin = sortedVotes[0][1].votes - (sortedVotes[1] ? sortedVotes[1][1].votes : 0);
        let isTie = margin === 0;
    
        let details = "";
        for (const [generator_name, generator_data] of sortedVotes) {
            details += `<p>${generator_name}: ${generator_data.votes} votes</p>`;
            details += "<ul>";
            for (const text of generator_data.texts) {
                details += `<li><pre class="responseText">${text}</pre></li>`;
            }
            details += "</ul>";
        }
    
        if (isTie) {
            $("#resultsTitle").text("It's a tie!");
        } else {
            $("#resultsTitle").text("Winner:");
            $("#winner").text(winner);
            $("#margin").text(margin);
        }
    
        $("#detailedResults").html(details);
        $("#resultsContainer").show();
    }
        
    

    $("#swipeLeft").click(function () {
        results[currentTest].votes = 0;
        currentTest++;
        showNextResult();
    });

    $("#swipeRight").click(function () {
        results[currentTest].votes = 1;
        currentTest++;
        showNextResult();
    });

    function fetchResults() {
        if (completed === 0) {
            // Show the loading message
            $('#testForm').hide();
            $.post("/fetch-text")
                .done((data) => {
                    if (data.status === "waiting") {
                        setTimeout(fetchResults, 500); // Retry after 500ms
                    } else if (data.status === "completed") {
                        completed = 1;
                        // Hide the loading message
                        $("#loadingMessage").hide();
                        // Do any final processing or display here, if needed
                        console.log("Generation completed");
                    } else {
                        results.push(data);
                        updateResultsCounter();
                        showNextResult();
                        fetchResults(); // Fetch the next result immediately
                    }
                })
                .fail((error) => {
                    console.error("Error fetching text:", error);
                });
        }
    }
});

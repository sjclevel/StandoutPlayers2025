import os
import requests


def init_gemini(multimodal=False):
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY environment variable not set")

    import google.generativeai as genai
    genai.configure(api_key=api_key)

    if multimodal:
        generation_config = {
            "temperature": 1,
            "top_p": 0.95,
            "top_k": 40,
            "max_output_tokens": 8192,
            "response_mime_type": "text/plain",
        }
        model_name = "gemini-1.5-flash"
    else:
        generation_config = {
            "temperature": 0.7,
            "top_p": 0.8,
            "top_k": 40,
            "max_output_tokens": 2048,
        }
        model_name = "gemini-2.0-flash-exp"

    return genai.GenerativeModel(
        model_name=model_name,
        generation_config=generation_config,
    )


def upload_to_gemini(path, mime_type=None):
    """
    Uploads a file to Gemini for multimodal analysis
    """
    import google.generativeai as genai
    file = genai.upload_file(path, mime_type=mime_type)
    print(f"Uploaded file '{file.display_name}' as: {file.uri}")
    return file


def get_player_info(player_id, season=None):
    """
    Fetches detailed information about an MLB player from the Stats API.
    """
    if not player_id or str(player_id) == "1":  # Skip invalid IDs
        return None

    try:
        url = f"https://statsapi.mlb.com/api/v1/people/{player_id}"
        params = {}
        if season:
            params['season'] = season

        response = requests.get(url, params=params)
        if response.status_code == 404:
            print(f"Player ID {player_id} not found")
            return None
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Error fetching player information: {e}")
        return None


def analyze_video(player_name, homer_data):
    try:
        model = init_gemini()

        prompt = f"""
        Please analyze this home run by {player_name} with these metrics:

        Exit Velocity: {homer_data.get('ExitVelocity', 'N/A')} mph
        Hit Distance: {homer_data.get('HitDistance', 'N/A')} feet
        Launch Angle: {homer_data.get('LaunchAngle', 'N/A')}°

        Format your response in plain text with no special characters or markdown:

        Example format:
        Exit Velocity: This is an elite exit velocity that ranks in the 95th percentile...
        Launch Angle: This launch angle is in the optimal range...
        Hit Distance: The ball traveled an impressive distance...
        """

        response = model.generate_content(prompt)
        analysis_text = response.text.replace('*',
                                              '').replace('**',
                                                          '').replace('#', '')

        return {
            'text': analysis_text,
            'metrics': {
                'exit_velocity': float(homer_data.get('ExitVelocity', 0)),
                'estimated_distance': float(homer_data.get('HitDistance', 0)),
                'launch_angle': float(homer_data.get('LaunchAngle', 0))
            }
        }
    except Exception as e:
        print(f"Error analyzing video: {e}")
        return {
            'text': "Error analyzing video",
            'metrics': {
                'exit_velocity': 0,
                'estimated_distance': 0,
                'launch_angle': 0
            }
        }


def get_all_home_runs(player_name):
    """
    Get all home runs for a player.
    """
    try:
        from main import home_runs_df
        clean_player_name = player_name.lower().strip()
        names = clean_player_name.split()
        last_name = names[-1] if names else ""
        first_name = names[0] if names else ""

        # Convert title column to string type and handle NaN values
        home_runs_df['title'] = home_runs_df['title'].astype(str)

        # Look for titles that contain "homers" or "home run" after the player name
        homer_pattern = f"({clean_player_name.lower()}).*?(homers|home run)"
        player_home_runs = home_runs_df[
            home_runs_df['title'].str.lower().str.match(homer_pattern,
                                                        case=False)]

        # If no matches, try matching last name and first name separately
        if player_home_runs.empty and last_name and first_name:
            player_home_runs = home_runs_df[
                home_runs_df['title'].str.lower().str.contains(last_name,
                                                               case=False)
                & home_runs_df['title'].str.lower().str.contains(first_name,
                                                                 case=False)]

        if not player_home_runs.empty:
            return player_home_runs[[
                'title', 'video', 'ExitVelocity', 'HitDistance', 'LaunchAngle'
            ]].to_dict('records')
        return []
    except Exception as e:
        print(f"Error finding home runs: {e}")
        return []


if __name__ == "__main__":
    pass

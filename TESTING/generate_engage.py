import pandas as pd
import numpy as np

# Load your existing CSV
df = pd.read_csv("users_commodities_india_geo.csv")

np.random.seed(42)

# ---- State based engagement multiplier (regional behavior differences) ----
state_multiplier = {
    "Maharashtra": 1.3,
    "Gujarat": 1.2,
    "Karnataka": 1.1,
    "Tamil Nadu": 1.15,
    "Uttar Pradesh": 0.9,
    "Rajasthan": 0.85,
    "Punjab": 1.05,
    "Haryana": 1.0,
    "West Bengal": 0.95,
    "Madhya Pradesh": 0.9
}

# Default multiplier
default_multiplier = 1.0

# Function to generate engagement with outliers
def generate_engagement(row):
    multiplier = state_multiplier.get(row['state'], default_multiplier)
    
    # Base values
    followers = int(np.random.normal(500 * multiplier, 200))
    like_count = int(np.random.normal(50 * multiplier, 20))
    comment_count = int(np.random.normal(20 * multiplier, 10))
    share_count = int(np.random.normal(10 * multiplier, 5))
    screentime = round(np.random.normal(1.5 * multiplier, 0.5), 2)
    
    # Add outliers (influencers / very active users)
    if np.random.rand() < 0.05:  # 5% outliers
        followers *= np.random.randint(5, 15)
        like_count *= np.random.randint(5, 10)
        comment_count *= np.random.randint(5, 10)
        share_count *= np.random.randint(5, 10)
        screentime *= np.random.randint(2, 4)
    
    return pd.Series([max(0, followers),
                      max(0, like_count),
                      max(0, comment_count),
                      max(0, share_count),
                      max(0, screentime)])

# Apply to dataframe
df[['followers', 'like_count', 'comment_count', 'share_count', 'screentime_hours']] = df.apply(generate_engagement, axis=1)

# Save new CSV
df.to_csv("users_with_engagement.csv", index=False)

print("New file created: users_with_engagement.csv")
print(df.head())
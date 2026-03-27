import pandas as pd
import random

# Commodities and roles
commodities = ["rice", "sugar", "cotton"]
roles = ["trader", "broker", "exporter"]

# 10 cities per state
state_cities = {
    "Maharashtra": ["Mumbai", "Pune", "Nagpur", "Nashik", "Aurangabad", "Solapur", "Kolhapur", "Amravati", "Nanded", "Jalgaon"],
    "Gujarat": ["Ahmedabad", "Surat", "Vadodara", "Rajkot", "Bhavnagar", "Jamnagar", "Junagadh", "Gandhinagar", "Anand", "Navsari"],
    "Rajasthan": ["Jaipur", "Jodhpur", "Udaipur", "Kota", "Bikaner", "Ajmer", "Alwar", "Bharatpur", "Sikar", "Pali"],
    "Uttar Pradesh": ["Lucknow", "Kanpur", "Varanasi", "Agra", "Meerut", "Prayagraj", "Bareilly", "Ghaziabad", "Noida", "Gorakhpur"],
    "Madhya Pradesh": ["Indore", "Bhopal", "Jabalpur", "Gwalior", "Ujjain", "Sagar", "Satna", "Ratlam", "Rewa", "Katni"],
    "Karnataka": ["Bengaluru", "Mysuru", "Mangaluru", "Hubli", "Belagavi", "Davangere", "Ballari", "Shivamogga", "Tumkur", "Udupi"],
    "Tamil Nadu": ["Chennai", "Coimbatore", "Madurai", "Salem", "Tiruchirappalli", "Erode", "Vellore", "Thoothukudi", "Dindigul", "Thanjavur"],
    "Telangana": ["Hyderabad", "Warangal", "Nizamabad", "Karimnagar", "Khammam", "Ramagundam", "Mahbubnagar", "Adilabad", "Suryapet", "Miryalaguda"],
    "West Bengal": ["Kolkata", "Howrah", "Durgapur", "Asansol", "Siliguri", "Malda", "Kharagpur", "Haldia", "Raiganj", "Krishnanagar"],
    "Punjab": ["Ludhiana", "Amritsar", "Jalandhar", "Patiala", "Bathinda", "Mohali", "Hoshiarpur", "Pathankot", "Moga", "Phagwara"]
}

# Number of rows/users
num_rows = 1000

data = []

for user_id in range(1, num_rows + 1):
    # Select commodities (1 to 3)
    num_commodities = random.randint(1, 3)
    selected_commodities = ";".join(random.sample(commodities, num_commodities))
    
    role = random.choice(roles)
    
    # Select state and city
    state = random.choice(list(state_cities.keys()))
    city = random.choice(state_cities[state])
    
    # Quantity
    min_qty = random.randint(20, 100)
    max_qty = min_qty + random.randint(50, 300)
    
    data.append([
        user_id,
        selected_commodities,
        role,
        city,
        state,
        min_qty,
        max_qty
    ])

# Create DataFrame
df = pd.DataFrame(data, columns=[
    "user_id",
    "commodity",
    "role",
    "city",
    "state",
    "min_quantity_mt",
    "max_quantity_mt"
])

# Save CSV
df.to_csv("users_commodities_india.csv", index=False)

print("CSV Generated: users_commodities_india.csv")
df.head()